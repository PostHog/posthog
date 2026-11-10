import gzip
import json
import base64
from datetime import UTC, datetime, timedelta

from django.test import SimpleTestCase

from parameterized import parameterized

from products.customer_analytics.backend.logic.account_automations import (
    CompletedWorkflowStep,
    decode_run_context,
    get_expected_resume_at,
    get_last_completed_step,
    matches_account,
)


class TestAccountRunEvidence(SimpleTestCase):
    @parameterized.expand(
        [
            ("system", {"event": {"event": "$account_updated", "distinct_id": "account:abc"}}, True),
            (
                "actor",
                {
                    "event": {
                        "event": "$account_updated",
                        "distinct_id": "staff",
                        "properties": {"account_external_id": "example"},
                    }
                },
                True,
            ),
            (
                "batch",
                {"accountAudience": True, "event": {"event": "$batch_hog_flow_invocation", "distinct_id": "example"}},
                True,
            ),
            ("person_batch", {"event": {"event": "$batch_hog_flow_invocation", "distinct_id": "example"}}, False),
            ("person_event", {"event": {"event": "$pageview", "distinct_id": "account:abc"}}, False),
            (
                "other_account",
                {"event": {"event": "$account_updated", "properties": {"account_external_id": "other"}}},
                False,
            ),
        ]
    )
    def test_account_identity_from_compressed_saved_context(self, _name: str, context: dict, expected: bool) -> None:
        stored = base64.b64encode(gzip.compress(json.dumps(context).encode())).decode()
        assert matches_account(decode_run_context(stored), "abc", "example") is expected

    @parameterized.expand(
        [
            ("transition", ["Executing action a", "Workflow moved to action b"], 1),
            ("final", ["Executing action a", "Workflow completed"], 1),
            ("error_continue", ["Executing action a", "a Errored: failed", "Workflow moved to action b"], None),
            ("filtered", ["a Skipped due to filter conditions", "Workflow moved to action b"], None),
            ("pause", ["Executing action a", "Workflow will pause until 2030-01-01"], None),
            ("expired_start", ["Workflow completed"], None),
            (
                "trigger_mismatch",
                ["Executing action trigger", "Workflow trigger did not match the event.", "Workflow completed"],
                None,
            ),
            (
                "skipped_send",
                [
                    "Executing action a",
                    "Skipping send: recipient is on the suppression list.",
                    "Workflow moved to action b",
                ],
                None,
            ),
            (
                "later_error",
                ["Executing action a", "Workflow moved to action b", "Executing action b", "b Errored: failed"],
                1,
            ),
        ]
    )
    def test_last_completed_step_requires_execution_evidence(
        self, _name: str, messages: list[str], completed_index: int | None
    ) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        logs = [(start + timedelta(seconds=i), message) for i, message in enumerate(messages)]
        assert get_last_completed_step(logs, exit_action_ids={"a"}) == (
            CompletedWorkflowStep(action_id="a", completed_at=logs[completed_index][0])
            if completed_index is not None
            else None
        )

    def test_ambiguous_log_order_does_not_claim_a_successful_step(self) -> None:
        timestamp = datetime(2026, 1, 1, tzinfo=UTC)
        logs = [
            (timestamp, message)
            for message in ["Executing action a", "Workflow moved to action b", "a Errored: failed"]
        ]
        assert get_last_completed_step(logs, exit_action_ids=set()) is None

    @parameterized.expand(
        [
            (
                ["Executing action [Action:a]", "Workflow moved to action [Action:b]", "Executing action [Action:b]"],
                "a",
            ),
            (["Executing action a", "Executing action b", "Workflow moved to action c"], None),
        ]
    )
    def test_tied_transitions_only_name_an_unambiguous_completed_step(
        self, messages: list[str], expected_action_id: str | None
    ) -> None:
        timestamp = datetime(2026, 1, 1, tzinfo=UTC)
        assert get_last_completed_step([(timestamp, message) for message in messages], exit_action_ids=set()) == (
            CompletedWorkflowStep(action_id=expected_action_id, completed_at=timestamp)
        )

    @parameterized.expand(
        [
            ("waiting", ["Workflow will pause until 2026-01-02T00:00:00Z"], True),
            ("resumed", ["Workflow will pause until 2026-01-02T00:00:00Z", "Executing action send"], False),
            ("completed", ["Workflow will pause until 2026-01-02T00:00:00Z", "Workflow completed"], False),
            ("past", ["Workflow will pause until 2025-12-31T00:00:00Z"], False),
            ("missing", [], False),
            ("invalid", ["Workflow will pause until invalid"], False),
            ("naive", ["Workflow will pause until 2026-01-02T00:00:00"], False),
            ("non_delay", ["Executing action fetch", "Workflow will pause until 2026-01-02T00:00:00Z"], False),
        ]
    )
    def test_resume_time_requires_a_retained_future_pause_without_later_execution(
        self, _name: str, messages: list[str], waiting: bool
    ) -> None:
        now = datetime(2026, 1, 1, tzinfo=UTC)
        logs = [(now + timedelta(seconds=i), message) for i, message in enumerate(["Executing action wait", *messages])]
        assert get_expected_resume_at(logs, now=now, delay_action_ids={"wait"}) == (
            now + timedelta(days=1) if waiting else None
        )
