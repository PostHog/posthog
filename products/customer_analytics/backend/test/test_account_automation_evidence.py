from datetime import UTC, datetime, timedelta

from django.test import SimpleTestCase

from parameterized import parameterized

from products.customer_analytics.backend.logic.account_automations import (
    CompletedWorkflowStep,
    get_expected_resume_at,
    get_last_completed_step,
)


class TestAccountRunEvidence(SimpleTestCase):
    @parameterized.expand(
        [
            ("transition", ["Executing action a", "Workflow moved to action b"], 1),
            ("final", ["Executing action a", "Workflow completed"], 1),
            (
                "error_continue",
                ["Executing action a", "[Action:a] Errored: failed", "Workflow moved to action b"],
                None,
            ),
            (
                "filtered",
                ["Executing action a", "[Action:a] Skipped due to filter conditions", "Workflow moved to action b"],
                None,
            ),
            (
                "custom_output",
                [
                    "Executing action a",
                    "[Action:a] skip_count=0 Errored: 0 did not match=0 would not trigger=0",
                    "Workflow moved to action b",
                ],
                2,
            ),
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
                    "[Action:a] Skipping send: recipient is on the suppression list.",
                    "Workflow moved to action b",
                ],
                None,
            ),
            (
                "later_error",
                [
                    "Executing action a",
                    "Workflow moved to action b",
                    "Executing action b",
                    "[Action:b] Errored: failed",
                ],
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
            for message in ["Executing action a", "Workflow moved to action b", "[Action:a] Errored: failed"]
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
            (
                "custom_output",
                ["Workflow will pause until 2026-01-02T00:00:00Z", "[Action:wait] skip_count=0 Errored: 0"],
                True,
            ),
            ("failed", ["Workflow will pause until 2026-01-02T00:00:00Z", "[Action:wait] Errored: failed"], False),
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
