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


@parameterized.expand(
    [
        ("started_on_cloud", emit_slo_started, STARTED, "US", True),
        ("started_self_hosted", emit_slo_started, STARTED, None, False),
        ("completed_on_cloud", emit_slo_completed, COMPLETED, "EU", True),
        ("completed_self_hosted", emit_slo_completed, COMPLETED, None, False),
    ]
)
def test_slo_events_only_reach_posthog_from_cloud(
    _name: str,
    emit: Callable[..., None],
    properties: SloStartedProperties | SloCompletedProperties,
    cloud_deployment: str | None,
    expected_sent: bool,
) -> None:
    with (
        override_settings(CLOUD_DEPLOYMENT=cloud_deployment),
        patch("posthog.slo.events.posthoganalytics.capture") as capture,
    ):
        emit("distinct-id", properties)

    assert capture.called is expected_sent
