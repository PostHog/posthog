import json
from datetime import UTC, datetime
from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from products.alerts.backend.logic.insight_alert_destinations import hog_slack_attachments
from products.alerts.backend.logic.insight_alert_message import insight_alert_slack_properties
from products.alerts.backend.platform_alert_slack import render_insight_slack_message
from products.alerts_platform.backend.facade.contracts import AlertEventKind, AnnouncedTransition
from products.cdp.backend.validation import generate_template_bytecode

from common.hogvm.python.execute import execute_bytecode


class TestInsightAlertMessage(SimpleTestCase):
    def _properties(self, **overrides: Any) -> dict[str, Any]:
        return insight_alert_slack_properties(
            **{
                "breaches": ["Request time reached 240 ms, above 200 ms."],
                "metric_name": "Request time",
                "summary": None,
                "verdict": None,
                "investigation_status": None,
                "detected_at": "23 Oct 2026, 10:00 UTC",
                "allowed_root": "https://example.com/",
                **overrides,
            }
        )

    def test_compiled_message_preserves_controls(self) -> None:
        properties = self._properties(
            affected_dates=["2026-10-23T14:00:00+00:00"],
            project_timezone="America/Toronto",
            affected_interval="hour",
        )
        properties.update(
            {
                "alert_name": "Response time",
                "alert_id": "sample-alert",
                "insight_id": "sample01",
                "insight_name": "Request time",
                "breaches": "Request time reached 240 ms.",
            }
        )
        globals_ = {
            "event": {"properties": properties, "timestamp": "2026-10-23T10:00:00Z"},
            "project": {"url": "https://example.com/project/1", "name": "Example project"},
        }

        def render(value: Any) -> Any:
            if isinstance(value, list):
                if value and value[0] == "_H":
                    return execute_bytecode(value, globals=globals_).result
                return [render(item) for item in value]
            if isinstance(value, dict):
                return {key: render(item) for key, item in value.items()}
            return value

        blocks = render(
            generate_template_bytecode(hog_slack_attachments(), set(), function_type="internal_destination")
        )
        assert "23 Oct 2026, 10:00 to 23 Oct 2026, 11:00 (America/Toronto)" in json.dumps(blocks)
        assert "https://example.com/project/1" in json.dumps(blocks)
        assert blocks[-1]["blocks"][-1]["elements"][-1]["action_id"] == "insight_alert_snooze"
        assert len(blocks[-1]["blocks"][-1]["elements"][-1]["options"]) == 5

    def test_untrusted_breach_names_stay_literal(self) -> None:
        message = self._properties(breaches=["<!channel> [click](https://untrusted.example) reached 240 ms."])
        content = message["slack_alert_details"]
        elements = content["elements"][0]["elements"][0]["elements"]
        assert all(element["type"] == "text" for element in elements)
        assert any(element["text"] == "240 ms" and element.get("style", {}).get("code") for element in elements)

    def test_summary_keeps_emphasis_and_blocks_external_links(self) -> None:
        message = self._properties(
            summary="- **Request time** reached **240 ms** at _10:00 UTC_.\n- [Report](https://untrusted.example/report)"
        )
        content = message["slack_alert_details"]
        elements = content["elements"][0]["elements"][0]["elements"]
        assert any(element.get("style", {}).get("bold") for element in elements)
        assert any(element.get("style", {}).get("italic") for element in elements)
        assert '"type": "link"' not in json.dumps(content)

    def test_grouped_summary_preserves_groups_and_next_step(self) -> None:
        details = [
            {"group": f"Region {index}", "observed": "240 ms", "limit": "200 ms", "previous": "100 ms"}
            for index in range(5)
        ]
        details[-1]["other_groups"] = "3"
        message = self._properties(
            breach_details=details,
            metric_description="Request time by region.",
            verdict="true_positive",
            next_step="Compare the regions in the insight.",
        )
        blocks = message["slack_alert_details"]["elements"]
        assert all(f"Region {index}" in json.dumps(blocks) for index in range(5))
        assert "3 more affected groups" in json.dumps(blocks)
        assert "Unusual change confirmed" in json.dumps(blocks)
        assert "Compare the regions" in json.dumps(blocks)

    @parameterized.expand(
        [
            ("fall_back", "2026-11-01T05:00:00+00:00", "01:00 EDT", "01:00 EST"),
            ("spring_forward", "2026-03-08T06:00:00+00:00", "01:00 EST", "03:00 EDT"),
            ("spring_forward_naive", "2026-03-08 01:00:00", "01:00", "03:00"),
        ]
    )
    def test_period_distinguishes_daylight_saving_offsets(self, _name: str, start: str, first: str, last: str) -> None:
        properties = self._properties(
            affected_dates=[start], affected_interval="hour", project_timezone="America/Toronto"
        )
        timing = properties["slack_alert_timing"]["text"]["text"]
        assert first in timing
        assert last in timing

    @parameterized.expand(
        [
            ("that_fired", "original-insight"),
            # A transition recorded before the check stored the short id would otherwise link to
            # `/insights/None`, which is a live button onto a dead page.
            ("it_does_not_know", None),
        ]
    )
    def test_native_message_links_to_the_insight(self, _name: str, short_id: str | None) -> None:
        now = datetime(2026, 1, 1, tzinfo=UTC)
        detail: dict[str, Any] = {"alert_id": "00000000-0000-4000-8000-000000000001"}
        if short_id is not None:
            detail["insight_short_id"] = short_id
        transition = AnnouncedTransition(
            grouping_key="",
            kind=AlertEventKind.FIRING,
            episode_started_at=now,
            value=240,
            labels={},
            condition={},
            source_config={},
            error_message=None,
            occurred_at=now,
            source_detail=detail,
        )
        content = render_insight_slack_message(
            team_id=1,
            transition=transition,
            alert_name="Example alert",
            alert_url="https://example.com/alert",
            project=None,
            image=None,
        )
        assert content is not None
        links = [
            element["url"]
            for element in content.attachments[1]["blocks"][-1]["elements"]
            if element.get("text", {}).get("text") == "📊 View insight"
        ]
        assert [link.split("/project/")[-1] for link in links] == ([f"1/insights/{short_id}"] if short_id else [])

    @parameterized.expand(
        [
            ("says_what_it_is", "Example alert", "Insight alert ‘Example alert’ triggered"),
            # `text` is mrkdwn, so an alert a project member named `<!channel>` would otherwise
            # broadcast to everyone in the channel on every firing.
            ("cannot_speak_as_slack_markup", "<!channel>", "Insight alert ‘&lt;!channel&gt;’ triggered"),
        ]
    )
    def test_the_text_slack_notifies_with(self, _name: str, alert_name: str, expected: str) -> None:
        # The card is an attachment, which a push notification and a screen reader do not read.
        now = datetime(2026, 1, 1, tzinfo=UTC)
        transition = AnnouncedTransition(
            grouping_key="",
            kind=AlertEventKind.FIRING,
            episode_started_at=now,
            value=240,
            labels={},
            condition={},
            source_config={},
            error_message=None,
            occurred_at=now,
            source_detail={"alert_id": "00000000-0000-4000-8000-000000000001"},
        )
        content = render_insight_slack_message(
            team_id=1,
            transition=transition,
            alert_name=alert_name,
            alert_url="https://example.com/alert",
            project=None,
            image=None,
        )
        assert content is not None
        assert content.text == expected
        # The attachment fallback is plain text, so it keeps the name as written.
        assert alert_name in content.attachments[0]["fallback"]

    def test_native_anomaly_message_shows_the_affected_period(self) -> None:
        now = datetime(2026, 1, 2, tzinfo=UTC)
        transition = AnnouncedTransition(
            grouping_key="",
            kind=AlertEventKind.FIRING,
            episode_started_at=now,
            value=240,
            labels={},
            condition={},
            source_config={},
            error_message=None,
            occurred_at=now,
            source_detail={
                "alert_id": "00000000-0000-4000-8000-000000000001",
                "insight_short_id": "original-insight",
                "is_anomaly": True,
                "triggered_dates": ["2026-01-01"],
                "interval": "day",
            },
        )
        content = render_insight_slack_message(
            team_id=1,
            transition=transition,
            alert_name="Example alert",
            alert_url="https://example.com/alert",
            project=None,
            image=None,
        )
        assert content is not None
        assert "Affected period" in str(content.attachments)
