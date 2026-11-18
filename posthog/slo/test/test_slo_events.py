from collections.abc import Callable

from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized

from posthog.slo.events import emit_slo_completed, emit_slo_started
from posthog.slo.types import SloArea, SloCompletedProperties, SloOperation, SloOutcome, SloStartedProperties

STARTED = SloStartedProperties(area=SloArea.ANALYTIC_PLATFORM, operation=SloOperation.EXPORT, team_id=1)
COMPLETED = SloCompletedProperties(
    area=SloArea.ANALYTIC_PLATFORM, operation=SloOperation.EXPORT, team_id=1, outcome=SloOutcome.SUCCESS
)


CLOUD = {"CLOUD_DEPLOYMENT": "US", "DEBUG": False, "TEST": False}
LOCAL_DEV = {"CLOUD_DEPLOYMENT": None, "DEBUG": True, "TEST": False}
SELF_HOSTED = {"CLOUD_DEPLOYMENT": None, "DEBUG": False, "TEST": False}


@parameterized.expand(
    [
        ("started_on_cloud", emit_slo_started, STARTED, CLOUD, True),
        ("started_in_local_dev", emit_slo_started, STARTED, LOCAL_DEV, True),
        ("started_self_hosted", emit_slo_started, STARTED, SELF_HOSTED, False),
        ("completed_on_cloud", emit_slo_completed, COMPLETED, CLOUD, True),
        ("completed_self_hosted", emit_slo_completed, COMPLETED, SELF_HOSTED, False),
    ]
)
def test_slo_events_never_reach_posthog_from_self_hosted(
    _name: str,
    emit: Callable[..., None],
    properties: SloStartedProperties | SloCompletedProperties,
    run_mode_settings: dict[str, object],
    expected_sent: bool,
) -> None:
    with (
        override_settings(**run_mode_settings),
        patch("posthog.slo.events.posthoganalytics.capture") as capture,
    ):
        emit("distinct-id", properties)

    assert capture.called is expected_sent
