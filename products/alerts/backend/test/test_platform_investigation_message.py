from datetime import UTC, datetime, timedelta
from typing import Any, cast

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models.scoping import team_scope
from posthog.schema_enums import AlertState
from posthog.tasks.alerts.investigation_wording import SAFETY_NET_LINE
from posthog.utils import absolute_uri

from products.alerts.backend.models.alert import InvestigationStatus
from products.alerts.backend.models.investigation import InsightAlertInvestigation
from products.alerts.backend.platform_alert_legacy_events import emit_insight_legacy_events
from products.alerts.backend.platform_alert_slack import render_insight_slack_message
from products.alerts.backend.platform_alert_wording import VERDICT_CHANGED_KIND, describe_insight_transition
from products.alerts.backend.platform_investigation import verdict_change_evaluation_key
from products.alerts.backend.test.insight_alerts import create_insight_alert
from products.alerts_platform.backend.facade import testing as platform_testing
from products.alerts_platform.backend.facade.contracts import (
    AlertDeliveryRequest,
    AlertEventKind,
    AnnouncedTransition,
    EvaluationAnnouncement,
    LegacyEventEmission,
    MessageDetail,
    SourceKind,
)
from products.alerts_platform.backend.facade.enums import HoldReleasedBy
from products.notebooks.backend.facade import api as notebooks

EPISODE = datetime(2026, 10, 20, 8, 0, tzinfo=UTC)
FIRED_AT = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
KEY = "slot:2026-10-20T09:00:00+00:00"
OWN_BREACH = "Signups (50) is less than lower threshold (100)"
ANOMALY_HEAD = "Anomaly detected on 2026-10-20."
SUMMARY = "Signups fell after the **release**."
METRICS_SUMMARY = "queue.depth moved up to 420.00 (baseline 100.00, 4.2x)."
TEASER = "Signups fell after the release."


class TestInvestigatedFiringMessages(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.alert = create_insight_alert(self.team, name="Signups dropped", detector_config={"type": "zscore"})
        with team_scope(self.team.id):
            self.configuration_id = platform_testing.create_configuration(
                team_id=self.team.id,
                name="alert",
                source_kind=SourceKind.INSIGHT,
                check_interval_minutes=60,
                recurrence_unit="hour",
                legacy_configuration_id=self.alert.id,
            ).id
        self.notebook = notebooks.create_notebook(self.team.id, title="Investigation", content=None)
        self.notebook_url = absolute_uri(f"/notebooks/{self.notebook.short_id}")

    def _investigation(
        self,
        key: str,
        *,
        status: str = InvestigationStatus.DONE,
        verdict: str | None = None,
        at: datetime = FIRED_AT,
        kind: str = InsightAlertInvestigation.Kind.AGENT,
        summary: str | None = None,
    ) -> None:
        with time_machine.travel(at, tick=False):
            InsightAlertInvestigation.objects.for_team(self.team.id).create(
                team=self.team,
                alert_configuration=self.alert,
                configuration_id=self.configuration_id,
                evaluation_key=key,
                episode_started_at=EPISODE,
                kind=kind,
                status=status,
                verdict=verdict,
                summary=summary or (SUMMARY if verdict else None),
                notebook_id=self.notebook.id if verdict else None,
                evaluated={"value": 50.0, "triggered_dates": ["2026-10-20"]},
            )

    def _released_by(self, released_by: HoldReleasedBy) -> None:
        platform_testing.release_held_delivery(
            team_id=self.team.id,
            configuration_id=self.configuration_id,
            evaluation_key=KEY,
            released_by=released_by,
            at=FIRED_AT,
        )

    def _transition(self, kind: str = AlertEventKind.FIRING, key: str = KEY) -> AnnouncedTransition:
        return AnnouncedTransition(
            grouping_key="",
            kind=cast(AlertEventKind, kind),
            episode_started_at=EPISODE,
            value=50.0,
            labels={},
            condition={},
            source_config={},
            error_message=None,
            occurred_at=FIRED_AT,
            evaluation_key=key,
            source_detail={"breaches": [OWN_BREACH], "alert_id": str(self.alert.id), "is_anomaly": True},
            configuration_id=str(self.configuration_id),
        )

    def _event_properties(self, transition: AnnouncedTransition) -> dict[str, Any]:
        request = AlertDeliveryRequest(
            source=SourceKind.INSIGHT,
            team_id=self.team.id,
            configuration_id=str(self.configuration_id),
            evaluation_key=transition.evaluation_key,
            destination_alert_id=str(self.alert.id),
            event_ids_by_kind={},
        )
        announcement = EvaluationAnnouncement(
            configuration_id=str(self.configuration_id),
            source=SourceKind.INSIGHT,
            alert_name=self.alert.name,
            consecutive_failures=0,
            transitions=(transition,),
        )
        emission = LegacyEventEmission(transition=transition, sends_message=True, incident_action=None)
        with patch("products.alerts.backend.platform_alert_legacy_events.emit_alert_internal_events") as emit:
            emit_insight_legacy_events(request=request, announcement=announcement, emissions=[emission])
        (event,) = emit.call_args.kwargs["events"]
        return event.properties

    @staticmethod
    def _investigation_label(properties: dict[str, Any]) -> str | None:
        for section in properties["slack_alert_details"]["elements"]:
            texts = [element.get("text") for element in section.get("elements", [])]
            if texts[:1] == ["Investigation: "]:
                return texts[1]
        return None

    @parameterized.expand(
        [
            ("the_agent_is_off", None, None, None, [OWN_BREACH], False, None),
            # A firing of an alert that does not gate goes out before the agent answers.
            ("an_ungated_firing", InvestigationStatus.PENDING, None, None, [OWN_BREACH], False, "In progress"),
            ("a_refused_claim", InvestigationStatus.SKIPPED, None, None, [OWN_BREACH], False, None),
            (
                "a_verdict_released_the_firing",
                InvestigationStatus.DONE,
                "true_positive",
                HoldReleasedBy.VERDICT,
                [ANOMALY_HEAD, "Investigation verdict: True positive.", TEASER],
                True,
                "Unusual change confirmed",
            ),
            (
                "the_safety_net_sent_it_without_a_verdict",
                InvestigationStatus.RUNNING,
                None,
                HoldReleasedBy.SAFETY_NET,
                [ANOMALY_HEAD, SAFETY_NET_LINE],
                False,
                "In progress",
            ),
            (
                "the_claim_was_refused_after_the_hold",
                InvestigationStatus.PENDING,
                None,
                HoldReleasedBy.CLAIM_REFUSED,
                [OWN_BREACH],
                False,
                "In progress",
            ),
        ]
    )
    def test_a_firing_states_what_its_investigation_found(
        self,
        _name: str,
        status: str | None,
        verdict: str | None,
        released_by: HoldReleasedBy | None,
        breaches: list[str],
        links_notebook: bool,
        label: str | None,
    ) -> None:
        if status is not None:
            self._investigation(KEY, status=status, verdict=verdict)
        if released_by is not None:
            self._released_by(released_by)
        expected_breaches = [
            *breaches,
            *([f"See {self.notebook_url} for the full investigation."] if links_notebook else []),
        ]

        properties = self._event_properties(self._transition())

        assert properties["breaches"] == "\n".join(expected_breaches)
        assert properties.get("investigation_notebook_url") == (self.notebook_url if links_notebook else None)
        assert self._investigation_label(properties) == label
        description = describe_insight_transition(project_id=self.team.id, transition=self._transition())
        assert description.details == (MessageDetail(label="Threshold breached", value="\n".join(expected_breaches)),)

    @parameterized.expand(
        [
            ("released_after_its_run", InvestigationStatus.DONE, HoldReleasedBy.VERDICT, [OWN_BREACH, METRICS_SUMMARY]),
            (
                "sent_by_the_safety_net_after_it_failed",
                InvestigationStatus.FAILED,
                HoldReleasedBy.SAFETY_NET,
                [OWN_BREACH],
            ),
        ]
    )
    def test_a_metrics_firing_keeps_its_own_breaches_and_adds_its_explanation(
        self, _name: str, status: str, released_by: HoldReleasedBy, breaches: list[str]
    ) -> None:
        self._investigation(
            KEY,
            status=status,
            kind=InsightAlertInvestigation.Kind.METRICS,
            summary=METRICS_SUMMARY if status == InvestigationStatus.DONE else None,
        )
        self._released_by(released_by)

        properties = self._event_properties(self._transition())

        assert properties["breaches"] == "\n".join(breaches)
        assert properties.get("investigation_notebook_url") is None
        # Email, PagerDuty and webhooks read the same breaches, so they carry the explanation too.
        description = describe_insight_transition(project_id=self.team.id, transition=self._transition())
        assert description.details == (MessageDetail(label="Threshold breached", value="\n".join(breaches)),)

    def test_a_changed_verdict_follows_up_with_the_change(self) -> None:
        self._investigation("slot:2026-10-20T08:00:00+00:00", verdict="true_positive", at=EPISODE)
        self._investigation(KEY, verdict="false_positive")
        follow_up = self._transition(VERDICT_CHANGED_KIND, verdict_change_evaluation_key(KEY))
        expected = [
            "Investigation verdict changed from True positive to False positive while this alert keeps firing.",
            ANOMALY_HEAD,
            "Investigation verdict: False positive.",
            TEASER,
            f"See {self.notebook_url} for the full investigation.",
        ]

        properties = self._event_properties(follow_up)

        assert properties["breaches"] == "\n".join(expected)
        assert properties["state"] == AlertState.FIRING.value
        assert properties["investigation_notebook_url"] == self.notebook_url
        slack = render_insight_slack_message(
            team_id=self.team.id,
            transition=follow_up,
            alert_name=self.alert.name,
            alert_url="https://example.com/alert",
            project=None,
            image=None,
        )
        assert slack is not None
        (actions,) = [block for block in slack.attachments[-1]["blocks"] if block["type"] == "actions"]
        button = actions["elements"][0]
        assert button == {
            "url": self.notebook_url,
            "text": {"text": "🔎 View investigation", "type": "plain_text"},
            "type": "button",
        }

    def test_a_firing_of_an_earlier_episode_does_not_count_as_the_previous_verdict(self) -> None:
        with time_machine.travel(EPISODE - timedelta(days=1), tick=False):
            InsightAlertInvestigation.objects.for_team(self.team.id).create(
                team=self.team,
                alert_configuration=self.alert,
                configuration_id=self.configuration_id,
                evaluation_key="slot:yesterday",
                episode_started_at=EPISODE - timedelta(days=1),
                kind=InsightAlertInvestigation.Kind.AGENT,
                status=InvestigationStatus.DONE,
                verdict="true_positive",
            )
        self._investigation(KEY, verdict="inconclusive")
        self._released_by(HoldReleasedBy.VERDICT)

        properties = self._event_properties(self._transition())

        assert properties["breaches"].splitlines()[0] == ANOMALY_HEAD
