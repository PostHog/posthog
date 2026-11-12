from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.scoping import team_scope
from posthog.schema_enums import AlertState
from posthog.tasks.alerts.utils import RenderedInsightChart, trigger_alert_hog_functions

from products.alerts.backend.platform_alert_legacy_events import emit_insight_legacy_events, insight_chart_image
from products.alerts.backend.platform_source_cycle import platform_upsert_of
from products.alerts.backend.test.insight_alerts import create_insight_alert
from products.alerts_platform.backend.facade import testing as platform_testing
from products.alerts_platform.backend.facade.contracts import (
    AlertDeliveryRequest,
    AlertEventKind,
    AnnouncedTransition,
    EvaluationAnnouncement,
    IncidentAction,
    LegacyEventEmission,
    MessageImage,
    SourceKind,
)

_MODULE = "products.alerts.backend.platform_alert_legacy_events"
CHECKED_AT = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
CHART_URL = "https://example.com/chart.png"
_EMITTER = "products.alerts.backend.platform_alert_legacy_events"
# What the platform adds on top of what the insight stack sends: the pre-rendered Slack card.
_SLACK_CARD_PROPERTIES = {
    "slack_alert_tags",
    "slack_alert_type",
    "slack_alert_status",
    "slack_alert_timing",
    "slack_alert_detected_at",
    "slack_alert_details",
}


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
        upsert = platform_upsert_of(self.alert)
        assert upsert is not None
        with team_scope(self.team.id):
            self.configuration_id = platform_testing.create_configuration(
                team_id=self.team.id,
                name=upsert.name,
                source_kind=SourceKind.INSIGHT,
                source_config=upsert.source_config,
                check_interval_minutes=upsert.check_interval_minutes,
                recurrence_unit=upsert.recurrence_unit,
                legacy_configuration_id=self.alert.id,
            ).id

    def _emit(self, *emissions: LegacyEventEmission, configuration_id: str | None = None) -> list[Any]:
        request = AlertDeliveryRequest(
            source=SourceKind.INSIGHT,
            team_id=self.team.id,
            configuration_id=configuration_id or str(self.configuration_id),
            evaluation_key="slot:1",
            destination_alert_id=str(self.alert.id),
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
        incident_action: IncidentAction | None = None,
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
        return LegacyEventEmission(transition=transition, sends_message=sends_message, incident_action=incident_action)

    @parameterized.expand(
        [
            ("without_a_chart", {}, {}),
            (
                "with_a_chart",
                {"insight_chart_asset_id": 7, "insight_chart_render_user_id": 3},
                {"insight_chart_url": CHART_URL},
            ),
            (
                "with_an_ai_verdict",
                {"triggered_metadata": {"detector_type": "llm", "rationale": "Signups fell to 12.", "kind": "drop"}},
                {"anomaly_rationale": "Signups fell to 12.", "anomaly_kind": "drop"},
            ),
        ]
    )
    def test_a_firing_emits_the_properties_the_insight_stack_sends(
        self, _name: str, stored: dict[str, Any], sent: dict[str, str]
    ) -> None:
        breaches = ["The insight value (150) is more than upper threshold (100)", "A second series breached"]
        with patch("posthog.tasks.alerts.utils.produce_alert_internal_event") as produce:
            trigger_alert_hog_functions(self.alert, {"breaches": "\n".join(breaches), **sent})

        with patch(f"{_EMITTER}.insight_chart_url", return_value=CHART_URL) as mint:
            (event,) = self._emit(self._emission(detail={"breaches": breaches, "is_anomaly": True, **stored}))

        assert event.event_name == produce.call_args.kwargs["event_name"]
        expected = produce.call_args.kwargs["properties"]
        assert {key: event.properties[key] for key in expected} == expected
        # Named rather than left open, so a property the insight stack never sends cannot appear
        # here unnoticed and reach a customer's HogFunction template.
        assert set(event.properties) - set(expected) == _SLACK_CARD_PROPERTIES
        assert event.properties["slack_alert_type"] == "Anomaly detected"
        # The URL opens the chart without a login, so it is minted for the user that rendered it.
        if "insight_chart_asset_id" in stored:
            assert mint.call_args.kwargs["chart"] == RenderedInsightChart(asset_id=7, render_user_id=3)

    def test_a_firing_states_the_transition_it_announces_not_the_alert_row(self) -> None:
        # The platform writes neither column, so a platform-owned alert's row keeps whatever the
        # insight stack last left there — `Not firing` once the shadow check stops.
        self.alert.state = AlertState.NOT_FIRING.value
        self.alert.last_checked_at = CHECKED_AT - timedelta(days=30)
        self.alert.save(update_fields=["state", "last_checked_at"])

        (event,) = self._emit(self._emission(detail={"breaches": ["above 100"]}))

        assert event.properties["state"] == AlertState.FIRING.value
        assert event.properties["last_checked_at"] == CHECKED_AT.isoformat()

    @parameterized.expand(
        [
            ("an_unknown_timezone", {"timezone": "Mars/Olympus"}),
            ("a_breach_row_that_is_not_a_dict", {"breach_details": ["above 100"]}),
            ("a_breach_row_without_an_observed_value", {"breach_details": [{"group": "Chrome"}]}),
        ]
    )
    def test_a_detail_the_card_cannot_be_built_from_still_emits_the_event(
        self, _name: str, detail: dict[str, Any]
    ) -> None:
        # The card is an extra. Losing it must not take the event, because the event is what every
        # HogFunction destination — Slack, webhook, email — listens on.
        (event,) = self._emit(self._emission(detail={"breaches": ["above 100"], **detail}))

        assert event.properties["alert_id"] == str(self.alert.id)
        assert event.properties["breaches"] == "above 100"

    @parameterized.expand(
        [
            ("an_error", AlertEventKind.ERRORED, True, None),
            ("a_held_message", AlertEventKind.FIRING, False, None),
            ("a_deleted_alert", AlertEventKind.FIRING, True, "01900000-0000-0000-0000-00000000dead"),
        ]
    )
    def test_nothing_the_insight_stack_would_not_send_is_emitted(
        self, _name: str, kind: AlertEventKind, sends_message: bool, configuration_id: str | None
    ) -> None:
        assert self._emit(self._emission(kind, sends_message=sends_message), configuration_id=configuration_id) == []

    @parameterized.expand(
        [
            (
                "an_opened_firing",
                AlertEventKind.FIRING,
                True,
                IncidentAction.TRIGGER,
                ["$insight_alert_firing", "$insight_alert_incident_opened"],
            ),
            (
                "a_silent_resolve",
                AlertEventKind.CHECK,
                False,
                IncidentAction.RESOLVE,
                ["$insight_alert_incident_closed"],
            ),
        ]
    )
    def test_an_incident_edge_emits_its_incident_event_beside_any_message(
        self,
        _name: str,
        kind: AlertEventKind,
        sends_message: bool,
        action: IncidentAction,
        expected: list[str],
    ) -> None:
        events = self._emit(
            self._emission(
                kind, sends_message=sends_message, detail={"breaches": ["above 100"]}, incident_action=action
            )
        )

        assert [event.event_name for event in events] == expected
        assert all(event.properties["alert_id"] == str(self.alert.id) for event in events)
        if action == IncidentAction.RESOLVE:
            assert events[0].properties == self.alert.internal_event_properties(
                state=AlertState.NOT_FIRING.value, last_checked_at=CHECKED_AT
            )

    @parameterized.expand(
        [
            ("a_firing", AlertEventKind.FIRING, True, IncidentAction.TRIGGER, False),
            ("a_resolve_after_its_insight_is_deleted", AlertEventKind.CHECK, False, IncidentAction.RESOLVE, True),
        ]
    )
    def test_an_alert_with_no_insight_row_reaches_its_hogfunctions(
        self,
        _name: str,
        kind: AlertEventKind,
        sends_message: bool,
        action: IncidentAction,
        insight_deleted: bool,
    ) -> None:
        upsert = platform_upsert_of(self.alert)
        assert upsert is not None
        with team_scope(self.team.id):
            native_id = platform_testing.create_configuration(
                team_id=self.team.id,
                name="Native signups dropped",
                source_kind=SourceKind.INSIGHT,
                source_config=upsert.source_config,
                check_interval_minutes=upsert.check_interval_minutes,
                recurrence_unit=upsert.recurrence_unit,
                owner="platform",
                legacy_configuration_id=None,
            ).id
        if insight_deleted:
            self.alert.insight.deleted = True
            self.alert.insight.save(update_fields=["deleted"])

        events = self._emit(
            self._emission(
                kind, sends_message=sends_message, detail={"breaches": ["above 100"]}, incident_action=action
            ),
            configuration_id=str(native_id),
        )

        assert events
        assert {(event.properties["alert_id"], event.properties["alert_name"]) for event in events} == {
            (str(native_id), "Native signups dropped")
        }


class TestInsightChartImage(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "a_firing_with_a_chart",
                AlertEventKind.FIRING,
                {"insight_chart_asset_id": 7, "insight_chart_render_user_id": 3},
                True,
            ),
            ("a_firing_without_one", AlertEventKind.FIRING, {}, False),
            (
                "an_error",
                AlertEventKind.ERRORED,
                {"insight_chart_asset_id": 7, "insight_chart_render_user_id": 3},
                False,
            ),
        ]
    )
    def test_a_native_message_shows_the_chart_a_firing_rendered(
        self, _name: str, kind: AlertEventKind, detail: dict[str, Any], shown: bool
    ) -> None:
        transition = AnnouncedTransition(
            grouping_key="",
            kind=kind,
            episode_started_at=None,
            value=150.0,
            labels={},
            condition={},
            source_config={},
            error_message=None,
            occurred_at=datetime(2026, 10, 20, 9, 0, tzinfo=UTC),
            source_detail=detail,
        )

        with patch(f"{_EMITTER}.insight_chart_url", return_value=CHART_URL):
            image = insight_chart_image(team_id=2, transition=transition)

        assert image == (MessageImage(url=CHART_URL, alt_text="Insight chart") if shown else None)
