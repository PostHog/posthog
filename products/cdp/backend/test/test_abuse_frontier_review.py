import json
import time
from typing import Any

import pytest
import time_machine
from unittest.mock import patch

import httpx
from parameterized import parameterized

from products.cdp.backend.abuse import frontier, judge, rules
from products.cdp.backend.abuse.classifier import HogFunctionContent
from products.cdp.backend.abuse.frontier import Pending, SkipReason, StoredVerdict
from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.cdp.backend.tasks import abuse_classification
from products.cdp.backend.test.abuse_support import (
    RULE_FREE_HOG,
    SCORES,
    SECRET_VALUE,
    AbuseClassificationTestCase,
    decision_payload,
)
from products.cdp.backend.test.test_abuse_review import PROBE_VERDICT, model_message

PROBE_HOG = "fetch('http://169.254.169.254/latest', {'body': {'text': inputs.message}})"
LOW_SCORES = {**SCORES, "runtime_escape": 0.05}
QUEUED = {"frontier_review_queued": True}
SKIPPED_PARKED = {"frontier_review_queued": False, "frontier_review_skipped": "parked_true_positive"}
SKIPPED_UNCHANGED = {"frontier_review_queued": False, "frontier_review_skipped": "unchanged"}


@pytest.mark.parametrize(
    "pending, now, expected",
    [
        pytest.param(
            Pending(first_saved_at=1000.0, due_at=1120.0),
            1100.0,
            Pending(first_saved_at=1000.0, due_at=1220.0),
            id="a_save_in_the_countdown_pushes_it_back",
        ),
        pytest.param(
            Pending(first_saved_at=1000.0, due_at=1590.0),
            1550.0,
            Pending(first_saved_at=1000.0, due_at=1600.0),
            id="a_long_burst_is_still_reviewed",
        ),
    ],
)
def test_a_save_in_a_burst_pushes_the_review_back(pending: Pending, now: float, expected: Pending) -> None:
    assert frontier.pushed_back(pending, now) == expected


@pytest.mark.parametrize(
    "pending, expected",
    [
        pytest.param(Pending(first_saved_at=900.0, due_at=1020.0), 20.0, id="saved_again_since"),
        pytest.param(Pending(first_saved_at=900.0, due_at=1000.0), None, id="due"),
        pytest.param(None, None, id="entry_lost_from_the_cache"),
    ],
)
def test_the_task_waits_until_the_burst_is_over(pending: Pending | None, expected: float | None) -> None:
    assert frontier.seconds_to_wait(pending, 1000.0) == expected


def _stored(verdict: str, fingerprint: str = "same") -> StoredVerdict:
    return StoredVerdict(
        verdict=verdict, parked=verdict == "true_positive", fingerprint=fingerprint, reviewed_at=1000.0
    )


@pytest.mark.parametrize(
    "switched_on, stored, expected",
    [
        pytest.param(False, None, SkipReason.SWITCHED_OFF, id="switched_off"),
        pytest.param(True, None, None, id="never_reviewed"),
        pytest.param(True, _stored("true_positive", "other"), SkipReason.PARKED_TRUE_POSITIVE, id="parked"),
        pytest.param(True, _stored("false_positive"), SkipReason.UNCHANGED, id="false_positive_unchanged"),
        pytest.param(True, _stored("uncertain"), SkipReason.UNCHANGED, id="uncertain_unchanged"),
        pytest.param(True, _stored("false_positive", "other"), None, id="false_positive_changed"),
    ],
)
def test_a_verdict_skips_the_review_until_it_no_longer_covers_the_function(
    switched_on: bool, stored: StoredVerdict | None, expected: SkipReason | None
) -> None:
    assert frontier.skip_reason(switched_on=switched_on, stored=stored, fingerprint="same") == expected


def _content(**overrides: Any) -> HogFunctionContent:
    fields: dict[str, Any] = {
        "type": "destination",
        "template_id": None,
        "code_modified_from_template": None,
        "hog": "fetch(inputs.url, {'body': {'text': inputs.message}})",
        "inputs_schema": [],
        "inputs": {
            "url": {"value": "https://hooks.example.com/orders"},
            "message": {"value": "Order placed, runbook at http://localhost:8000/runbook"},
        },
        "filters": {"events": [{"id": "$pageview"}]},
        "mappings": [],
        "masking": None,
    }
    return HogFunctionContent(**(fields | overrides))


def _fingerprint(content: HogFunctionContent) -> str:
    return frontier.fingerprint(content, rules.matched_rules(content), rules.has_outbound_call(content))


@pytest.mark.parametrize(
    "edit, same",
    [
        pytest.param(
            {
                "inputs": {
                    "url": {"value": "https://hooks.example.com/orders"},
                    "message": {"value": "Order shipped, runbook at http://localhost:8000/runbook"},
                }
            },
            True,
            id="message_text",
        ),
        pytest.param({"filters": {"events": [{"id": "order placed"}]}}, True, id="filters"),
        pytest.param({"hog": "fetch(inputs.url, {'body': inputs.message})"}, False, id="code"),
        pytest.param(
            {
                "inputs": {
                    "url": {"value": "https://catcher.example.org/orders"},
                    "message": {"value": "Order placed, runbook at http://localhost:8000/runbook"},
                }
            },
            False,
            id="request_host",
        ),
        pytest.param(
            {
                "inputs": {
                    "url": {"value": "https://hooks.example.com/orders"},
                    "message": {"value": "Order placed, runbook at http://127.0.0.1:8000/runbook"},
                }
            },
            False,
            id="flagged_host",
        ),
    ],
)
def test_the_fingerprint_changes_only_with_what_the_verdict_rests_on(edit: dict[str, Any], same: bool) -> None:
    assert (_fingerprint(_content(**edit)) == _fingerprint(_content())) is same


def test_the_task_outlasts_the_slowest_review() -> None:
    assert abuse_classification.REVIEW_SOFT_TIME_LIMIT_SECONDS > 2 * 2 * judge.REQUEST_TIMEOUT_SECONDS


class FakeBroker:
    """Holds queued reviews until the frozen clock reaches their countdown, as the Celery broker does."""

    def __init__(self) -> None:
        self.queued: list[tuple[float, dict[str, Any]]] = []

    def apply_async(self, *, kwargs: dict[str, Any], countdown: float) -> None:
        self.queued.append((time.time() + countdown, kwargs))

    def run_due(self) -> None:
        due = [kwargs for eta, kwargs in self.queued if eta <= time.time()]
        self.queued = [(eta, kwargs) for eta, kwargs in self.queued if eta > time.time()]
        for kwargs in due:
            abuse_classification.review_hog_function_for_abuse(**kwargs)


class TestFrontierReview(AbuseClassificationTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.flags.payload = {"frontier_review": True}
        self.jev_reply = httpx.Response(200, json=decision_payload(SCORES))
        self.review_reply = httpx.Response(200, json=model_message(json.dumps(PROBE_VERDICT)))
        self.broker = FakeBroker()
        for patcher in (
            patch.object(self.gateway, "handle", new=self.route),
            patch.object(
                abuse_classification.review_hog_function_for_abuse, "apply_async", new=self.broker.apply_async
            ),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def route(self, request: httpx.Request) -> httpx.Response:
        self.gateway.requests.append(request)
        return self.review_reply if request.url.path.endswith("/messages") else self.jev_reply

    def review_requests(self) -> list[httpx.Request]:
        return [request for request in self.gateway.requests if request.url.path.endswith("/messages")]

    def events(self, name: str) -> list[dict[str, Any]]:
        return [event["properties"] for event in self.captured_events() if event["event"] == name]

    def frontier_properties(self) -> dict[str, Any]:
        properties = self.events("cdp abuse classification")[-1]
        return {key: value for key, value in properties.items() if key.startswith("frontier_review")}

    def probe(self) -> HogFunction:
        return self.create_destination(
            hog=PROBE_HOG,
            inputs_schema=[{"key": "message", "type": "string", "label": "Message"}],
            inputs={"message": {"value": "Order placed"}},
            mappings=[],
            masking=None,
        )

    def save(self, hog_function: HogFunction, **changes: Any) -> None:
        for field, value in changes.items():
            setattr(hog_function, field, value)
        with self.committed():
            hog_function.save()

    def test_a_burst_of_saves_is_reviewed_once_on_its_latest_version(self) -> None:
        with time_machine.travel(time.time(), tick=False) as clock:
            probe = self.probe()
            assert self.frontier_properties() == {"frontier_review_queued": True}
            clock.shift(60)
            self.save(probe, hog=PROBE_HOG.replace("/latest", "/latest/meta-data"))
            assert self.frontier_properties() == {"frontier_review_queued": True}
            assert len(self.broker.queued) == 1
            clock.shift(61)
            self.broker.run_due()
            assert self.review_requests() == []
            clock.shift(60)
            self.broker.run_due()

        [request] = self.review_requests()
        assert "/latest/meta-data" in json.loads(request.content)["messages"][0]["content"]
        assert SECRET_VALUE not in request.content.decode()
        [review] = self.events("cdp abuse review")
        assert review["hog_function_id"] == str(probe.id)
        assert {key: review[key] for key in PROBE_VERDICT} == PROBE_VERDICT
        assert review["review_model"] == "claude-opus-4-8"
        assert (review["review_input_tokens"], review["review_output_tokens"]) == (4200, 300)
        assert review["rule_hits"] == ["internal_host"]
        assert review["score_runtime_escape"] == SCORES["runtime_escape"]
        assert review["admin_url"].endswith(f"/admin/cdp/hogfunction/{probe.id}/change/")
        assert self.broker.queued == []

    @parameterized.expand(
        [
            ("true_positive_parks", "true_positive", "code", SKIPPED_PARKED),
            ("false_positive_message_edit", "false_positive", "message", SKIPPED_UNCHANGED),
            ("false_positive_code_edit", "false_positive", "code", QUEUED),
            ("uncertain_message_edit", "uncertain", "message", SKIPPED_UNCHANGED),
            ("refused_message_edit", None, "message", QUEUED),
        ]
    )
    def test_a_verdict_decides_whether_the_next_save_is_reviewed(
        self, _name: str, verdict: str | None, edit: str, expected: dict[str, Any]
    ) -> None:
        if verdict is None:
            self.review_reply = httpx.Response(
                200,
                json=model_message("", stop_reason="refusal", stop_details={"type": "refusal", "category": "cyber"}),
            )
        else:
            answer = {**PROBE_VERDICT, "verdict": verdict}
            if verdict != "true_positive":
                answer["suggested_action"] = "none"
            self.review_reply = httpx.Response(200, json=model_message(json.dumps(answer)))
        with time_machine.travel(time.time(), tick=False) as clock:
            probe = self.probe()
            clock.shift(frontier.DEBOUNCE_SECONDS)
            self.broker.run_due()
            clock.shift(3600)
            if edit == "code":
                self.save(probe, hog=PROBE_HOG.replace("169.254.169.254", "127.0.0.1"))
            else:
                self.save(probe, inputs={"message": {"value": "Order shipped"}})

        [review] = self.events("cdp abuse review")
        if verdict is None:
            assert (review["review_failure"], review["refusal_category"]) == ("refused", "cyber")
            assert review["rule_hits"] == ["internal_host"]
        else:
            assert review["verdict"] == verdict
        assert self.frontier_properties() == expected
        assert len(self.broker.queued) == int(expected["frontier_review_queued"])

    @parameterized.expand(
        [
            ("gated_model_score", RULE_FREE_HOG, SCORES, 200),
            ("long_code_alone", RULE_FREE_HOG + "".join(f"\n// note {line}" for line in range(9000)), LOW_SCORES, 200),
            ("jev_down_without_a_rule_hit", RULE_FREE_HOG, SCORES, 503),
        ]
    )
    def test_a_save_that_would_not_have_alerted_is_not_reviewed(
        self, _name: str, hog: str, scores: dict[str, float], jev_status: int
    ) -> None:
        self.jev_reply = httpx.Response(jev_status, json=decision_payload(scores))

        self.create_destination(hog=hog)

        assert self.frontier_properties() == {"frontier_review_queued": False}
        assert self.broker.queued == []

    def test_a_probe_cleaned_within_the_countdown_is_still_reviewed(self) -> None:
        with time_machine.travel(time.time(), tick=False) as clock:
            probe = self.probe()
            clock.shift(30)
            self.jev_reply = httpx.Response(200, json=decision_payload(LOW_SCORES))
            self.save(probe, hog=RULE_FREE_HOG)
            assert self.frontier_properties() == {"frontier_review_queued": False}
            clock.shift(frontier.DEBOUNCE_SECONDS)
            self.broker.run_due()

        [request] = self.review_requests()
        assert RULE_FREE_HOG in json.loads(request.content)["messages"][0]["content"]
        assert len(self.events("cdp abuse review")) == 1

    def test_a_save_jev_could_not_score_is_reviewed_on_its_rule_hit(self) -> None:
        self.jev_reply = httpx.Response(503, json={})
        with time_machine.travel(time.time(), tick=False) as clock:
            self.probe()
            assert self.frontier_properties() == {"frontier_review_queued": True}
            clock.shift(frontier.DEBOUNCE_SECONDS)
            self.broker.run_due()

        [review] = self.events("cdp abuse review")
        assert (review["jev_error"], review["rule_hits"], review["verdict"]) == (
            "gateway_error",
            ["internal_host"],
            "true_positive",
        )

    def test_switching_the_review_off_drops_queued_reviews(self) -> None:
        with time_machine.travel(time.time(), tick=False) as clock:
            self.probe()
            self.flags.payload = {"frontier_review": False}
            clock.shift(frontier.DEBOUNCE_SECONDS)
            self.broker.run_due()

        assert self.review_requests() == []
        assert self.events("cdp abuse review") == []
