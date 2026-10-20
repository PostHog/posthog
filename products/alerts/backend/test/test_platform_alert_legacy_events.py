from datetime import UTC, datetime
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema_enums import AlertState
from posthog.tasks.alerts.utils import trigger_alert_hog_functions

from products.alerts.backend.platform_alert_legacy_events import emit_insight_legacy_events
from products.alerts.backend.test.insight_alerts import create_insight_alert
from products.alerts_platform.backend.facade.contracts import (
    AlertDeliveryRequest,
    AlertEventKind,
    AnnouncedTransition,
    EvaluationAnnouncement,
    LegacyEventEmission,
    SourceKind,
)

_MODULE = "products.alerts.backend.platform_alert_legacy_events"
CHECKED_AT = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
CHART_URL = "https://example.com/chart.png"


class TestInsightLegacyEvents(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.alert = create_insight_alert(
            self.team,
            name="Signups dropped",
            detector_config={"type": "zscore"},
            state=AlertState.FIRING.value,
            last_checked_at=CHECKED_AT,
        )

    def _emit(self, *emissions: LegacyEventEmission, alert_id: str | None = None) -> list[Any]:
        request = AlertDeliveryRequest(
            source=SourceKind.INSIGHT,
            team_id=self.team.id,
            configuration_id="cfg-1",
            evaluation_key="slot:1",
            destination_alert_id=alert_id or str(self.alert.id),
            event_ids_by_kind={},
        )
        announcement = EvaluationAnnouncement(
            configuration_id="cfg-1",
            source=SourceKind.INSIGHT,
            alert_name=self.alert.name,
            consecutive_failures=0,
            transitions=tuple(emission.transition for emission in emissions),
        )
        with patch(f"{_MODULE}.emit_alert_internal_events") as emit:
            emit_insight_legacy_events(request=request, announcement=announcement, emissions=emissions)
        return [event for call in emit.call_args_list for event in call.kwargs["events"]]

    @staticmethod
    def _emission(
        kind: AlertEventKind = AlertEventKind.FIRING,
        *,
        sends_message: bool = True,
        detail: dict[str, Any] | None = None,
    ) -> LegacyEventEmission:
        transition = AnnouncedTransition(
            grouping_key="",
            kind=kind,
            episode_started_at=CHECKED_AT,
            value=150.0,
            labels={},
            condition={},
            source_config={},
            error_message=None,
            occurred_at=CHECKED_AT,
            evaluation_key="slot:1",
            source_detail=detail or {},
        )
        return LegacyEventEmission(transition=transition, sends_message=sends_message, incident_action=None)

    @parameterized.expand([("without_a_chart", {}), ("with_a_chart", {"insight_chart_url": CHART_URL})])
    def test_a_firing_emits_the_properties_the_insight_stack_sends(self, _name: str, chart: dict[str, str]) -> None:
        breaches = ["The insight value (150) is more than upper threshold (100)", "A second series breached"]
        with patch("posthog.tasks.alerts.utils.produce_alert_internal_event") as produce:
            trigger_alert_hog_functions(self.alert, {"breaches": "\n".join(breaches), **chart})

        (event,) = self._emit(self._emission(detail={"breaches": breaches, **chart}))

        assert event.event_name == produce.call_args.kwargs["event_name"]
        assert event.properties == produce.call_args.kwargs["properties"]

    @parameterized.expand(
        [
            ("an_error", AlertEventKind.ERRORED, True, None),
            ("a_held_message", AlertEventKind.FIRING, False, None),
            ("a_deleted_alert", AlertEventKind.FIRING, True, "01900000-0000-0000-0000-00000000dead"),
        ]
    )
    def test_nothing_the_insight_stack_would_not_send_is_emitted(
        self, _name: str, kind: AlertEventKind, sends_message: bool, alert_id: str | None
    ) -> None:
        assert self._emit(self._emission(kind, sends_message=sends_message), alert_id=alert_id) == []
