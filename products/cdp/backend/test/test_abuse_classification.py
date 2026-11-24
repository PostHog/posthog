import json
from datetime import timedelta
from typing import Any

from django.utils import timezone

import httpx
from parameterized import parameterized

from posthog.models.organization import Organization
from posthog.utils import absolute_uri

from products.cdp.backend.abuse.classifier import MALICIOUS_QUESTIONS
from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.cdp.backend.tasks.abuse_classification import classify_hog_function_for_abuse
from products.cdp.backend.test.abuse_support import (
    RULE_FREE_HOG,
    SCORES,
    SECRET_VALUE,
    TEAM_FLAG,
    AbuseClassificationTestCase,
    decision_payload,
)

LOW_CONTROL_SCORES = {**SCORES, "normal_integration": 0.2}
SSRF_SCORES = {**SCORES, "internal_network": 0.6, "resource_exhaustion": 0.1, "normal_integration": 0.6}
NO_CALL_HOG = "print(event.properties.$ip)"
REQUEST_CATCHER_HOG = "fetch('https://webhook.site/0000')"
METADATA_HOG = "fetch('http://169.254.169.254/latest')"
ESTABLISHED = {
    "has_active_subscription": True,
    "age": timedelta(days=90),
    "customer_trust_scores": {"cdp_trigger_events": 7},
    "cdp_trust_score": 7,
}
NEW = {"has_active_subscription": False, "age": timedelta(days=2)}
NEVER_SYNCED = {"has_active_subscription": None, "age": timedelta(days=90)}
PAYING_FOR_TEN_DAYS = {"has_active_subscription": True, "age": timedelta(days=10)}
DEFAULT_THRESHOLDS = {"alert_threshold": 0.5, "block_threshold": 0.9}


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
            ("high_control_skips_a_moderate_model_alert", SCORES, None, RULE_FREE_HOG, [], False, False),
            ("low_control_keeps_a_moderate_model_alert", LOW_CONTROL_SCORES, None, RULE_FREE_HOG, [], True, False),
            (
                "high_control_still_alerts_and_blocks_at_the_block_threshold",
                {**SCORES, "resource_exhaustion": 0.9},
                None,
                RULE_FREE_HOG,
                [],
                True,
                True,
            ),
            (
                "thresholds_from_payload",
                SCORES,
                {"alert_threshold": 0.3, "block_threshold": 0.75},
                RULE_FREE_HOG,
                [],
                True,
                True,
            ),
            (
                "control_threshold_from_payload",
                SCORES,
                {"alert_threshold": 0.5, "block_threshold": 0.9, "control_threshold": 0.99},
                RULE_FREE_HOG,
                [],
                True,
                False,
            ),
            (
                "invalid_payload_uses_defaults",
                LOW_CONTROL_SCORES,
                {"alert_threshold": "high"},
                RULE_FREE_HOG,
                [],
                True,
                False,
            ),
            (
                "blocking_rule_overrides_the_model",
                SCORES,
                None,
                "fetch('http://169.254.169.254/latest')",
                ["internal_host"],
                True,
                True,
            ),
            (
                "alerting_rule_does_not_block",
                SCORES,
                {"alert_threshold": 0.9, "block_threshold": 0.95},
                "fetch('https://webhook.site/0000')",
                ["request_catcher"],
                True,
                False,
            ),
            (
                "security_callback_alerts_without_blocking",
                SCORES,
                {"alert_threshold": 0.9, "block_threshold": 0.95},
                "fetch('https://probe.oast.fun/')",
                ["security_callback"],
                True,
                False,
            ),
            (
                "rule_alerts_when_high_control_skips_the_model_alert",
                SCORES,
                None,
                "fetch('https://webhook.site/0000')",
                ["request_catcher"],
                True,
                False,
            ),
            ("ssrf_score_alerts_with_an_outbound_call", SSRF_SCORES, None, RULE_FREE_HOG, [], True, False),
            ("ssrf_score_is_ignored_without_an_outbound_call", SSRF_SCORES, None, NO_CALL_HOG, [], False, False, False),
            (
                "ssrf_score_at_the_block_threshold_is_ignored_without_an_outbound_call",
                {**SSRF_SCORES, "internal_network": 0.95},
                None,
                NO_CALL_HOG,
                [],
                False,
                False,
                False,
            ),
            (
                "other_risk_alerts_without_an_outbound_call",
                LOW_CONTROL_SCORES,
                None,
                NO_CALL_HOG,
                [],
                True,
                False,
                False,
            ),
            (
                "rule_alerts_without_an_outbound_call",
                {**SSRF_SCORES, "internal_network": 0.95},
                None,
                "if (event.properties.$current_url == 'http://127.0.0.1/') {\n  return\n}\nprint(event.event)",
                ["internal_host_reference"],
                True,
                False,
                False,
            ),
        ]
    )
    def test_a_verdict_is_captured_as_an_internal_event(
        self,
        _name: str,
        scores: dict[str, float],
        payload: dict | None,
        hog: str,
        rule_hits: list[str],
        would_alert: bool,
        would_block: bool,
        outbound_call: bool = True,
    ) -> None:
        self.gateway.response = httpx.Response(200, json=decision_payload(scores))
        self.flags.payload = payload
        hog_function = self.create_destination(template_id="template-webhook", hog=hog)

        [event] = self.captured_events()
        properties = event["properties"]
        assert isinstance(properties.pop("latency_ms"), float)
        assert len(properties.pop("content_hash")) == 64
        properties.pop("model_alert_gates")
        assert event["event"] == "cdp abuse classification"
        assert event["distinct_id"] == str(self.team.uuid)
        assert properties == {
            "team_id": self.team.id,
            "organization_id": str(self.organization.id),
            "organization_created_at": self.organization.created_at.isoformat(),
            "organization_age_days": 0,
            "organization_member_count": 1,
            "has_active_subscription": None,
            "cdp_trust_score": None,
            "account_tier": "standard",
            "hog_function_id": str(hog_function.id),
            "hog_function_type": "destination",
            "template_id": "template-webhook",
            "code_modified_from_template": None,
            "enabled": True,
            "trigger": "save",
            **{f"score_{question}": score for question, score in scores.items()},
            "risk_score": max(scores[question] for question in MALICIOUS_QUESTIONS),
            "rule_hits": rule_hits,
            "outbound_call": outbound_call,
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
            (
                "established_sets_a_moderate_model_alert_aside",
                ESTABLISHED,
                None,
                LOW_CONTROL_SCORES,
                RULE_FREE_HOG,
                "established",
                False,
                False,
                ["established_account"],
            ),
            (
                "established_records_each_gate_that_holds",
                ESTABLISHED,
                None,
                SCORES,
                RULE_FREE_HOG,
                "established",
                False,
                False,
                ["normal_integration", "established_account"],
            ),
            (
                "established_still_alerts_on_a_rule",
                ESTABLISHED,
                None,
                LOW_CONTROL_SCORES,
                REQUEST_CATCHER_HOG,
                "established",
                True,
                False,
                ["established_account"],
            ),
            (
                "established_still_blocks_on_a_blocking_rule",
                ESTABLISHED,
                None,
                LOW_CONTROL_SCORES,
                METADATA_HOG,
                "established",
                True,
                True,
                ["established_account"],
            ),
            (
                "established_alerts_and_blocks_at_the_block_threshold",
                ESTABLISHED,
                None,
                {**LOW_CONTROL_SCORES, "resource_exhaustion": 0.95},
                RULE_FREE_HOG,
                "established",
                True,
                True,
                [],
            ),
            (
                "new_keeps_a_moderate_model_alert",
                NEW,
                None,
                LOW_CONTROL_SCORES,
                RULE_FREE_HOG,
                "new",
                True,
                False,
                [],
            ),
            (
                "new_keeps_the_control_gate",
                NEW,
                None,
                SCORES,
                RULE_FREE_HOG,
                "new",
                False,
                False,
                ["normal_integration"],
            ),
            (
                "unsynced_subscription_counts_as_standard",
                NEVER_SYNCED,
                None,
                LOW_CONTROL_SCORES,
                RULE_FREE_HOG,
                "standard",
                True,
                False,
                [],
            ),
            (
                "new_account_over_the_member_limit_is_standard",
                {**NEW, "extra_members": 2},
                None,
                LOW_CONTROL_SCORES,
                RULE_FREE_HOG,
                "standard",
                True,
                False,
                [],
            ),
            (
                "established_age_from_payload",
                PAYING_FOR_TEN_DAYS,
                {**DEFAULT_THRESHOLDS, "established_min_age_days": 7},
                LOW_CONTROL_SCORES,
                RULE_FREE_HOG,
                "established",
                False,
                False,
                ["established_account"],
            ),
            (
                "invalid_cutoffs_use_defaults",
                PAYING_FOR_TEN_DAYS,
                {**DEFAULT_THRESHOLDS, "established_min_age_days": "a week"},
                LOW_CONTROL_SCORES,
                RULE_FREE_HOG,
                "standard",
                True,
                False,
                [],
            ),
            (
                "out_of_range_cutoffs_use_defaults",
                PAYING_FOR_TEN_DAYS,
                {**DEFAULT_THRESHOLDS, "established_min_age_days": 1_000_000_000},
                LOW_CONTROL_SCORES,
                RULE_FREE_HOG,
                "standard",
                True,
                False,
                [],
            ),
            (
                "infinite_cutoff_uses_defaults",
                PAYING_FOR_TEN_DAYS,
                {**DEFAULT_THRESHOLDS, "established_min_age_days": float("inf")},
                LOW_CONTROL_SCORES,
                RULE_FREE_HOG,
                "standard",
                True,
                False,
                [],
            ),
            (
                "integer_cutoff_beyond_float_range_uses_defaults",
                PAYING_FOR_TEN_DAYS,
                {**DEFAULT_THRESHOLDS, "established_min_age_days": 10**400},
                LOW_CONTROL_SCORES,
                RULE_FREE_HOG,
                "standard",
                True,
                False,
                [],
            ),
            (
                "fractional_string_cutoff_uses_defaults",
                PAYING_FOR_TEN_DAYS,
                {**DEFAULT_THRESHOLDS, "established_min_age_days": "7.0000000000000001"},
                LOW_CONTROL_SCORES,
                RULE_FREE_HOG,
                "standard",
                True,
                False,
                [],
            ),
            (
                "fractional_cutoff_uses_defaults",
                PAYING_FOR_TEN_DAYS,
                {**DEFAULT_THRESHOLDS, "established_min_age_days": 0.5},
                LOW_CONTROL_SCORES,
                RULE_FREE_HOG,
                "standard",
                True,
                False,
                [],
            ),
            (
                "huge_threshold_uses_defaults",
                ESTABLISHED,
                {"alert_threshold": 10**400, "block_threshold": 0.9},
                LOW_CONTROL_SCORES,
                RULE_FREE_HOG,
                "established",
                False,
                False,
                ["established_account"],
            ),
            (
                "new_cutoffs_from_payload",
                {"has_active_subscription": False, "age": timedelta(days=20), "extra_members": 2},
                {**DEFAULT_THRESHOLDS, "new_max_age_days": 21, "new_max_members": 3},
                LOW_CONTROL_SCORES,
                RULE_FREE_HOG,
                "new",
                True,
                False,
                [],
            ),
            (
                "established_alerts_at_the_configured_block_threshold",
                ESTABLISHED,
                {"alert_threshold": 0.5, "block_threshold": 0.75},
                LOW_CONTROL_SCORES,
                RULE_FREE_HOG,
                "established",
                True,
                True,
                [],
            ),
            (
                "non_numeric_trust_score_is_left_out",
                {**NEW, "customer_trust_scores": {"cdp_trigger_events": "high"}},
                None,
                LOW_CONTROL_SCORES,
                RULE_FREE_HOG,
                "new",
                True,
                False,
                [],
            ),
            (
                "unreadable_trust_scores_still_score",
                {**NEW, "customer_trust_scores": ["unexpected"]},
                None,
                LOW_CONTROL_SCORES,
                RULE_FREE_HOG,
                "new",
                True,
                False,
                [],
            ),
        ]
    )
    def test_the_account_tier_decides_whether_a_moderate_model_score_alerts(
        self,
        _name: str,
        account: dict[str, Any],
        payload: dict | None,
        scores: dict[str, float],
        hog: str,
        account_tier: str,
        would_alert: bool,
        would_block: bool,
        model_alert_gates: list[str],
    ) -> None:
        Organization.objects.filter(pk=self.organization.pk).update(
            has_active_subscription=account["has_active_subscription"],
            created_at=timezone.now() - account["age"],
            customer_trust_scores=account.get("customer_trust_scores", {}),
        )
        for member in range(account.get("extra_members", 0)):
            self._create_user(f"member-{member}@example.com")
        self.gateway.response = httpx.Response(200, json=decision_payload(scores))
        self.flags.payload = payload

        self.create_destination(hog=hog)

        [event] = self.captured_events()
        properties = event["properties"]
        assert {
            key: properties[key]
            for key in (
                "organization_age_days",
                "organization_member_count",
                "has_active_subscription",
                "cdp_trust_score",
                "account_tier",
                "would_alert",
                "would_block",
                "model_alert_gates",
            )
        } == {
            "organization_age_days": account["age"].days,
            "organization_member_count": 1 + account.get("extra_members", 0),
            "has_active_subscription": account["has_active_subscription"],
            "cdp_trust_score": account.get("cdp_trust_score"),
            "account_tier": account_tier,
            "would_alert": would_alert,
            "would_block": would_block,
            "model_alert_gates": model_alert_gates,
        }

    @parameterized.expand(
        [
            (
                "refused_with_a_blocking_rule",
                httpx.Response(503, json={"error": "busy"}),
                None,
                {},
                {"error": "gateway_error", "rule_hits": ["internal_host"], "would_alert": True, "would_block": True},
            ),
            (
                "unreachable_without_a_rule",
                None,
                httpx.ConnectError("connection refused"),
                {"hog": RULE_FREE_HOG},
                {
                    "error": "gateway_unreachable",
                    "rule_hits": [],
                    "outbound_call": True,
                    "would_alert": None,
                    "would_block": None,
                },
            ),
            (
                "unreadable_with_padded_input",
                httpx.Response(200, json=decision_payload({"internal_network": 0.1})),
                None,
                {
                    "hog": RULE_FREE_HOG,
                    "inputs_schema": [{"key": "padding", "type": "string"}],
                    "inputs": {"padding": {"value": "B" * 300_000}},
                },
                {"error": "invalid_answer", "rule_hits": [], "would_alert": None, "would_block": None},
            ),
            (
                "secret_input_runs_a_huge_range",
                httpx.Response(503, json={"error": "busy"}),
                None,
                {"hog": RULE_FREE_HOG, "inputs": {"api_key": {"value": "{range(1000000)}"}}},
                {"error": "gateway_error", "rule_hits": ["huge_range"], "would_alert": True, "would_block": False},
            ),
            (
                "secret_mapping_input_amplifies_a_string",
                httpx.Response(503, json={"error": "busy"}),
                None,
                {
                    "hog": RULE_FREE_HOG,
                    "mappings": [
                        {
                            "name": "Orders",
                            "inputs_schema": [{"key": "token", "type": "string", "secret": True}],
                            "inputs": {"token": {"value": "{replaceAll(event.event, '', 'xx')}"}},
                        }
                    ],
                },
                {
                    "error": "gateway_error",
                    "rule_hits": ["replace_amplification"],
                    "would_alert": True,
                    "would_block": False,
                },
            ),
        ]
    )
    def test_a_gateway_failure_is_captured_as_an_error_event_with_the_rule_verdict(
        self,
        _name: str,
        response: httpx.Response | None,
        error: Exception | None,
        overrides: dict[str, Any],
        expected: dict[str, Any],
    ) -> None:
        if response is not None:
            self.gateway.response = response
        self.gateway.error = error

        self.create_destination(**overrides)

        [event] = self.captured_events()
        properties = event["properties"]
        assert {key: properties.get(key) for key in expected} == expected
        assert "risk_score" not in properties

    @parameterized.expand(
        [
            (
                "long_code_is_cut",
                {"hog": "print('padding')\n" * 10_000 + "fetch('http://169.254.169.254/latest')"},
                True,
                None,
            ),
            (
                "padded_input_collapses_to_its_length",
                {
                    "hog": RULE_FREE_HOG,
                    "inputs_schema": [{"key": "padding", "type": "string"}],
                    "inputs": {"padding": {"value": "x" + "B" * 900_000 + "y"}},
                },
                False,
                'x["B" repeated 900000 times]y',
            ),
        ]
    )
    def test_an_oversized_function_fits_the_state_limit(
        self, _name: str, overrides: dict[str, Any], truncated: bool, padding_seen: str | None
    ) -> None:
        self.create_destination(**overrides)

        [body] = self.gateway.bodies()
        [event] = self.captured_events()
        state = json.loads(body)["state"]
        assert len(json.dumps(state, ensure_ascii=False, separators=(",", ":"))) <= 65_536
        assert event["properties"]["state_truncated"] is truncated
        if padding_seen is not None:
            assert state["inputs"]["padding"]["value"] == padding_seen

    @parameterized.expand(
        [
            ("name_only", {"name": "Renamed"}, 1),
            ("code", {"hog": "print('changed')"}, 2),
            ("disabling_a_scored_function", {"enabled": False}, 1),
            (
                "secret_rotated_to_a_benign_value",
                {
                    "inputs": {
                        "url": {"value": "https://hooks.example.com/orders"},
                        "api_key": {"value": "sk-live-rotated"},
                        "body": {"value": {"bytecode": "https://collector.example.net"}},
                    }
                },
                1,
            ),
            (
                "secret_input_that_matches_a_rule",
                {
                    "inputs": {
                        "url": {"value": "https://hooks.example.com/orders"},
                        "api_key": {"value": "{range(1000000)}"},
                        "body": {"value": {"bytecode": "https://collector.example.net"}},
                    }
                },
                2,
            ),
            (
                "secret_input_that_adds_an_outbound_call",
                {
                    "inputs": {
                        "url": {"value": "https://hooks.example.com/orders"},
                        "api_key": {"value": "{fetch(event.uuid)}"},
                        "body": {"value": {"bytecode": "https://collector.example.net"}},
                    }
                },
                2,
                {"hog": "print(event)"},
            ),
        ]
    )
    def test_a_resave_is_scored_again_only_when_its_content_changes(
        self, _name: str, changes: dict[str, Any], expected_requests: int, initial: dict[str, Any] | None = None
    ) -> None:
        hog_function = self.create_destination(**(initial or {}))

        for field, value in changes.items():
            setattr(hog_function, field, value)
        with self.committed():
            hog_function.save()

        assert len(self.gateway.requests) == expected_requests
        assert len(self.captured_events()) == expected_requests

    @parameterized.expand(
        [
            (
                "established_account_stops_paying",
                (True, timedelta(days=90)),
                (False, timedelta(days=90)),
                [False, True],
            ),
            ("new_account_grows_into_standard", (False, timedelta(days=2)), (False, timedelta(days=20)), [True]),
        ]
    )
    def test_an_unchanged_resave_is_scored_again_only_when_its_alert_gate_changes(
        self,
        _name: str,
        account_before: tuple[bool, timedelta],
        account_after: tuple[bool, timedelta],
        would_alert_per_event: list[bool],
    ) -> None:
        organization = Organization.objects.filter(pk=self.organization.pk)
        organization.update(has_active_subscription=account_before[0], created_at=timezone.now() - account_before[1])
        self.gateway.response = httpx.Response(200, json=decision_payload(LOW_CONTROL_SCORES))
        hog_function = self.create_destination(hog=RULE_FREE_HOG)

        organization.update(has_active_subscription=account_after[0], created_at=timezone.now() - account_after[1])
        with self.committed():
            hog_function.save()

        assert [event["properties"]["would_alert"] for event in self.captured_events()] == would_alert_per_event

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

    def test_a_queued_task_with_an_enabled_content_hash_still_scores_due_work(self) -> None:
        hog_function = self.create_destination(hog=RULE_FREE_HOG)
        HogFunction.objects.filter(pk=hog_function.pk).update(hog="print(event.event)")
        events_before = len(self.captured_events())

        classify_hog_function_for_abuse.delay(
            team_id=self.team.id, hog_function_id=str(hog_function.id), enabled_content_hash="a" * 64
        )

        assert len(self.gateway.requests) == 2
        [verdict] = self.captured_events()[events_before:]
        assert verdict["properties"]["hog_function_id"] == str(hog_function.id)
        assert "risk_score" in verdict["properties"]

    def test_an_undecryptable_secret_input_still_scores_the_public_config(self) -> None:
        hog_function = self.create_destination(hog=RULE_FREE_HOG)
        HogFunction.objects.filter(pk=hog_function.pk).update(
            hog="print(event.event)", encrypted_inputs="ciphertext without its key"
        )

        classify_hog_function_for_abuse(team_id=self.team.id, hog_function_id=str(hog_function.id))

        assert len(self.gateway.requests) == 2
        assert "risk_score" in self.captured_events()[-1]["properties"]

    def test_a_disabled_save_is_scored_and_enabling_it_reports_again(self) -> None:
        hog_function = self.create_destination(enabled=False)

        hog_function.enabled = True
        with self.committed():
            hog_function.save()

        assert len(self.gateway.requests) == 2
        assert [event["properties"]["enabled"] for event in self.captured_events()] == [False, True]

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
                "legacy_plugin_with_an_input_expression",
                "transformation",
                None,
                {
                    "template_id": "plugin-posthog-plugin-geoip",
                    "inputs_schema": [{"key": "value", "type": "string"}],
                    "inputs": {"value": {"value": "{event.uuid}"}},
                },
                1,
            ),
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
                "stock_template_with_a_secret_input_expression",
                "transformation",
                "stock",
                {
                    "inputs_schema": [{"key": "value", "type": "string", "secret": True}],
                    "inputs": {"value": {"value": "{event.uuid}"}},
                },
                1,
            ),
            (
                "stock_template_with_liquid_despite_templating_off",
                "transformation",
                "stock",
                {
                    "inputs_schema": [{"key": "value", "type": "string", "templating": False}],
                    "inputs": {"value": {"value": "{% if true %}x{% endif %}", "templating": "liquid"}},
                },
                1,
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
