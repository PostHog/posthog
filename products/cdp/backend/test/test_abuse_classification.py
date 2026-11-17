import json
from typing import Any

import httpx
from parameterized import parameterized

from posthog.utils import absolute_uri

from products.cdp.backend.tasks.abuse_classification import classify_hog_function_for_abuse
from products.cdp.backend.test.abuse_support import (
    SCORES,
    SECRET_VALUE,
    TEAM_FLAG,
    AbuseClassificationTestCase,
    decision_payload,
)


class TestAbuseClassification(AbuseClassificationTestCase):
    def test_a_saved_destination_is_scored_on_its_public_config(self) -> None:
        self.create_destination()

        [body] = self.gateway.bodies()
        assert SECRET_VALUE not in body
        assert "compiled" not in body
        assert "fetch(inputs.url" in body
        assert "169.254.169.254" in body
        assert "masking_key" in body
        assert "https://hooks.example.com/orders" in body
        assert "https://collector.example.net" in body
        assert self.gateway.requests[0].headers["X-PostHog-Privacy-Mode"] == "true"

    @parameterized.expand(
        [
            ("default_thresholds", None, True, False),
            ("thresholds_from_payload", {"alert_threshold": 0.3, "block_threshold": 0.75}, True, True),
            ("invalid_payload_uses_defaults", {"alert_threshold": "high"}, True, False),
        ]
    )
    def test_a_verdict_is_captured_as_an_internal_event(
        self, _name: str, payload: dict | None, would_alert: bool, would_block: bool
    ) -> None:
        self.flags.payload = payload
        hog_function = self.create_destination(template_id="template-webhook")

        [event] = self.captured_events()
        properties = event["properties"]
        assert isinstance(properties.pop("latency_ms"), float)
        assert len(properties.pop("content_hash")) == 64
        assert event["event"] == "cdp abuse classification"
        assert event["distinct_id"] == str(self.team.uuid)
        assert properties == {
            "team_id": self.team.id,
            "organization_id": str(self.organization.id),
            "organization_created_at": self.organization.created_at.isoformat(),
            "hog_function_id": str(hog_function.id),
            "hog_function_type": "destination",
            "template_id": "template-webhook",
            "code_modified_from_template": None,
            "enabled": True,
            "trigger": "save",
            "score_internal_network": 0.12,
            "score_resource_exhaustion": 0.8,
            "score_malformed_payload": 0.05,
            "score_unrelated_destination": 0.3,
            "score_normal_integration": 0.95,
            "risk_score": 0.8,
            "would_alert": would_alert,
            "would_block": would_block,
            "state_truncated": False,
            "model": "jevk5-0.2",
            "input_tokens": 512,
            "admin_url": absolute_uri(f"/admin/cdp/hogfunction/{hog_function.id}/change/"),
        }
        assert SECRET_VALUE not in json.dumps(event, default=str)

    @parameterized.expand(
        [
            ("refused", httpx.Response(503, json={"error": "busy"}), None, "gateway_error"),
            ("unreachable", None, httpx.ConnectError("connection refused"), "gateway_unreachable"),
            (
                "unreadable",
                httpx.Response(200, json=decision_payload({"internal_network": 0.1})),
                None,
                "invalid_answer",
            ),
        ]
    )
    def test_a_gateway_failure_is_captured_as_an_error_event(
        self, _name: str, response: httpx.Response | None, error: Exception | None, reason: str
    ) -> None:
        if response is not None:
            self.gateway.response = response
        self.gateway.error = error

        self.create_destination()

        [event] = self.captured_events()
        assert event["properties"]["error"] == reason
        assert "risk_score" not in event["properties"]

    def test_an_oversized_function_is_cut_to_the_state_limit_and_flagged(self) -> None:
        self.create_destination(hog="print('padding')\n" * 10_000 + "fetch('http://169.254.169.254/latest')")

        [body] = self.gateway.bodies()
        [event] = self.captured_events()
        assert len(json.dumps(json.loads(body)["state"], ensure_ascii=False, separators=(",", ":"))) <= 65_536
        assert event["properties"]["state_truncated"] is True

    @parameterized.expand([("name_only", {"name": "Renamed"}, 1), ("code", {"hog": "print('changed')"}, 2)])
    def test_a_resave_is_scored_again_only_when_its_content_changes(
        self, _name: str, changes: dict[str, str], expected_requests: int
    ) -> None:
        hog_function = self.create_destination()

        for field, value in changes.items():
            setattr(hog_function, field, value)
        with self.committed():
            hog_function.save()

        assert len(self.gateway.requests) == expected_requests

    @parameterized.expand([("gateway_down", True), ("capture_down", False)])
    def test_a_failed_classification_is_retried_on_the_next_save(self, _name: str, gateway_down: bool) -> None:
        if gateway_down:
            self.gateway.response = httpx.Response(503, json={"error": "busy"})
        else:
            self.capture.error = RuntimeError("capture unreachable")
        hog_function = self.create_destination()
        self.gateway.response = httpx.Response(200, json=decision_payload(SCORES))
        self.capture.error = None

        with self.committed():
            hog_function.save()

        assert len(self.gateway.requests) == 2
        assert "risk_score" in self.captured_events()[-1]["properties"]

    @parameterized.expand(
        [
            ("flag_off", False, None, {}),
            ("flag_error", None, RuntimeError("flags unavailable"), {}),
            ("site_destination", True, None, {"type": "site_destination"}),
            ("internal_destination", True, None, {"type": "internal_destination"}),
            ("deleted", True, None, {"deleted": True}),
            ("disabled", True, None, {"enabled": False}),
        ]
    )
    def test_nothing_is_classified(
        self, _name: str, enabled: bool | None, error: Exception | None, overrides: dict[str, Any]
    ) -> None:
        self.flags.enabled[TEAM_FLAG] = enabled
        self.flags.error = error

        self.create_destination(**overrides)

        assert self.gateway.requests == []
        assert self.captured_events() == []

    def test_a_draft_only_save_is_not_classified(self) -> None:
        hog_function = self.create_destination()

        hog_function.draft = {"hog": "print('staged edit')"}
        with self.committed():
            hog_function.save(update_fields=["draft"])

        assert len(self.gateway.requests) == 1

    @parameterized.expand([("flag_off", False, 0), ("already_scored", True, 1)])
    def test_a_queued_task_skips_work_that_is_no_longer_due(
        self, _name: str, flag_on: bool, expected_requests: int
    ) -> None:
        self.flags.enabled[TEAM_FLAG] = flag_on
        hog_function = self.create_destination()

        classify_hog_function_for_abuse(team_id=self.team.id, hog_function_id=str(hog_function.id))

        assert len(self.gateway.requests) == expected_requests

    def test_enabling_a_function_that_was_never_scored_scores_it(self) -> None:
        hog_function = self.create_destination(enabled=False)

        hog_function.enabled = True
        with self.committed():
            hog_function.save()

        assert len(self.gateway.requests) == 1

    @parameterized.expand(
        [
            ("stock_template_transformation", "transformation", "stock", {}, 0),
            ("edited_template_transformation", "transformation", "stock", {"hog": "return event // edited"}, 1),
            (
                "blank_template_transformation",
                "transformation",
                None,
                {"template_id": "template-blank-transformation"},
                1,
            ),
            ("custom_transformation", "transformation", None, {}, 1),
            ("legacy_plugin_transformation", "transformation", None, {"template_id": "plugin-posthog-plugin-geoip"}, 0),
            ("stock_template_destination", "destination", "stock", {}, 1),
            (
                "stock_template_with_an_input_expression",
                "transformation",
                "stock",
                {"inputs_schema": [{"key": "value", "type": "string"}], "inputs": {"value": {"value": "{event.uuid}"}}},
                1,
            ),
            (
                "stock_template_with_literal_inputs",
                "transformation",
                "stock",
                {"inputs_schema": [{"key": "value", "type": "string"}], "inputs": {"value": {"value": "literal"}}},
                0,
            ),
            (
                "stock_template_with_templating_off",
                "transformation",
                "stock",
                {
                    "inputs_schema": [{"key": "value", "type": "string", "templating": False}],
                    "inputs": {"value": {"value": "{not code}"}},
                },
                0,
            ),
        ]
    )
    def test_a_transformation_is_scored_only_when_it_runs_custom_code(
        self, _name: str, function_type: str, template: str | None, overrides: dict[str, Any], expected_requests: int
    ) -> None:
        if template == "stock":
            self.create_from_template(self.create_template(function_type), **overrides)
        else:
            self.create_destination(type=function_type, **overrides)

        assert len(self.gateway.requests) == expected_requests
