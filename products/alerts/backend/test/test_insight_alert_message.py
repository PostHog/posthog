import json
from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from products.alerts.backend.logic.insight_alert_destinations import _slack_attachments
from products.alerts.backend.logic.insight_alert_message import insight_alert_slack_properties
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

        blocks = render(generate_template_bytecode(_slack_attachments(), set(), function_type="internal_destination"))
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
            summary="- **Request time** reached **240 ms** at _10:00 UTC_.\n- [Report](https://untrusted.example/report)\n- https://untrusted.example/bare <https://untrusted.example/auto>"
        )
        content = message["slack_alert_details"]
        elements = content["elements"][0]["elements"][0]["elements"]
        assert any(element.get("style", {}).get("bold") for element in elements)
        assert any(element.get("style", {}).get("italic") for element in elements)
        assert '"type": "link"' not in json.dumps(content)
        text_elements = [
            element for section in content["elements"] for item in section["elements"] for element in item["elements"]
        ]
        assert not any(
            "untrusted.example" in element["text"] and not element.get("style", {}).get("code")
            for element in text_elements
        )

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
