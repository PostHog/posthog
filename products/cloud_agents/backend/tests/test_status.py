from collections.abc import Sequence

from django.test import SimpleTestCase

from parameterized import parameterized

from products.cloud_agents.backend.facade.enums import (
    CloudAgentReasoningEffort,
    CloudAgentRunStatus as Status,
    CloudAgentRunStatusReason as Reason,
    CloudAgentSessionStatus,
)
from products.cloud_agents.backend.logic import status as status_logic
from products.tasks.backend.facade.run_config import REASONING_EFFORTS

SWEEP = status_logic.QUOTA_SWEEP_CANCEL_SOURCE
RUN_ENDS = [None, "done", "cancelled", "error", "timeout", "usage_limit"]

# name, Tasks status, run end, cancel source, compute waived, pull request states, status, reason
MATRIX: list[tuple[str, str, str | None, str | None, bool, Sequence[str | None], Status, Reason | None]] = [
    *[
        (f"{task_status}_with_end_{run_end}", task_status, run_end, SWEEP, True, ["merged"], status, None)
        for task_status, status in [
            ("not_started", Status.QUEUED),
            ("queued", Status.QUEUED),
            ("in_progress", Status.RUNNING),
        ]
        for run_end in RUN_ENDS
    ],
    ("completed_no_pr", "completed", "done", None, False, [], Status.IDLE, Reason.TURN_CLOSED),
    ("completed_pr_open", "completed", "done", None, False, ["open"], Status.IDLE, Reason.TURN_CLOSED),
    ("completed_pr_draft", "completed", "done", None, False, ["draft"], Status.IDLE, Reason.TURN_CLOSED),
    ("completed_pr_unknown", "completed", "done", None, False, [None], Status.IDLE, Reason.TURN_CLOSED),
    ("completed_pr_merged", "completed", "done", None, False, ["merged"], Status.DONE, Reason.FINISHED),
    (
        "completed_one_of_two_merged",
        "completed",
        "done",
        None,
        False,
        ["closed", "merged"],
        Status.DONE,
        Reason.FINISHED,
    ),
    ("completed_merged_and_unknown", "completed", "done", None, False, [None, "merged"], Status.DONE, Reason.FINISHED),
    ("completed_pr_closed", "completed", "done", None, False, ["closed"], Status.DONE, Reason.CLOSED),
    ("completed_all_closed", "completed", "done", None, False, ["closed", "closed"], Status.DONE, Reason.CLOSED),
    (
        "completed_closed_and_open",
        "completed",
        "done",
        None,
        False,
        ["closed", "open"],
        Status.IDLE,
        Reason.TURN_CLOSED,
    ),
    (
        "completed_closed_and_unknown",
        "completed",
        "done",
        None,
        False,
        ["closed", None],
        Status.IDLE,
        Reason.TURN_CLOSED,
    ),
    # The sweep asked for a cancel and the turn ended first, so the run completed.
    ("completed_after_sweep_request", "completed", "done", SWEEP, False, [], Status.IDLE, Reason.TURN_CLOSED),
    ("failed_error", "failed", "error", None, False, [], Status.IDLE, Reason.UNEXPECTED_FAILURE),
    ("failed_timeout", "failed", "timeout", None, False, [], Status.IDLE, Reason.TIMED_OUT),
    ("failed_usage_limit", "failed", "usage_limit", None, False, [], Status.IDLE, Reason.CREDIT_SPENT),
    ("failed_infrastructure", "failed", "error", None, True, [], Status.IDLE, Reason.PROVISION_FAILED),
    ("failed_timeout_waived", "failed", "timeout", None, True, [], Status.IDLE, Reason.TIMED_OUT),
    ("failed_usage_limit_waived", "failed", "usage_limit", None, True, [], Status.IDLE, Reason.CREDIT_SPENT),
    # A merged pull request does not hide a failure: the run can still continue.
    ("failed_pr_merged", "failed", "error", None, False, ["merged"], Status.IDLE, Reason.UNEXPECTED_FAILURE),
    # The source of an earlier cancel request does not change why a run failed.
    ("failed_after_sweep_request", "failed", "error", SWEEP, False, [], Status.IDLE, Reason.UNEXPECTED_FAILURE),
    ("cancelled_by_api", "cancelled", "cancelled", "cloud_agents_api", False, [], Status.DONE, Reason.CANCELLED),
    ("cancelled_no_source", "cancelled", "cancelled", None, False, [], Status.DONE, Reason.CANCELLED),
    ("cancelled_other_source", "cancelled", "cancelled", "owner_deactivated", False, [], Status.DONE, Reason.CANCELLED),
    ("cancelled_by_sweep", "cancelled", "cancelled", SWEEP, False, [], Status.IDLE, Reason.CREDIT_SPENT),
    (
        "cancelled_by_sweep_pr_merged",
        "cancelled",
        "cancelled",
        SWEEP,
        False,
        ["merged"],
        Status.IDLE,
        Reason.CREDIT_SPENT,
    ),
    ("cancelled_pr_open", "cancelled", "cancelled", "cloud_agents_api", False, ["open"], Status.DONE, Reason.CANCELLED),
]


class TestStatusMapping(SimpleTestCase):
    @parameterized.expand(MATRIX)
    def test_run_status(
        self,
        _name: str,
        task_run_status: str,
        run_end: str | None,
        cancel_source: str | None,
        compute_waived: bool,
        pull_request_states: Sequence[str | None],
        expected_status: Status,
        expected_reason: Reason | None,
    ) -> None:
        result = status_logic.run_status_for(
            task_run_status,
            run_end=run_end,
            cancel_source=cancel_source,
            compute_waived=compute_waived,
            pull_request_states=pull_request_states,
        )
        assert (result.status, result.reason) == (expected_status, expected_reason)

    def test_every_reason_is_produced(self) -> None:
        assert {case[-1] for case in MATRIX} - {None} == set(Reason)

    @parameterized.expand(
        [
            ("unknown_status", "paused", None),
            ("failed_without_end", "failed", None),
            ("failed_with_unknown_end", "failed", "exploded"),
            ("failed_with_the_end_of_a_completed_run", "failed", "done"),
        ]
    )
    def test_state_that_tasks_does_not_have_is_an_error(
        self, _name: str, task_run_status: str, run_end: str | None
    ) -> None:
        with self.assertRaises(ValueError):
            status_logic.run_status_for(task_run_status, run_end=run_end)

    @parameterized.expand(
        [
            (Reason.TURN_CLOSED, False),
            (Reason.CANCELLED, False),
            (Reason.FINISHED, True),
            (Reason.CLOSED, True),
            (Reason.PROVISION_FAILED, True),
            (Reason.UNEXPECTED_FAILURE, True),
            (Reason.TIMED_OUT, True),
            (Reason.CREDIT_SPENT, True),
        ]
    )
    def test_status_detail(self, reason: Reason, has_detail: bool) -> None:
        detail = status_logic.status_detail_for(reason)
        assert (detail is not None) is has_detail
        # The usage limit text of Tasks names another product. The API text must not.
        assert "Desktop" not in (detail or "")
        assert status_logic.status_detail_for(None) is None

    @parameterized.expand(
        [
            (Status.QUEUED, ("not_started", "queued"), False),
            (Status.RUNNING, ("in_progress",), False),
            (Status.IDLE, ("completed", "failed", "cancelled"), True),
            (Status.DONE, ("completed", "failed", "cancelled"), True),
        ]
    )
    def test_tasks_statuses_of_a_list_filter(self, status: Status, expected: tuple[str, ...], shared: bool) -> None:
        assert status_logic.task_run_statuses_for(status) == expected
        assert status_logic.shares_task_run_statuses(status) is shared

    @parameterized.expand(
        [
            ("not_started", CloudAgentSessionStatus.QUEUED),
            ("queued", CloudAgentSessionStatus.QUEUED),
            ("in_progress", CloudAgentSessionStatus.RUNNING),
            ("completed", CloudAgentSessionStatus.ENDED),
            ("failed", CloudAgentSessionStatus.ENDED),
            ("cancelled", CloudAgentSessionStatus.ENDED),
        ]
    )
    def test_session_status(self, task_run_status: str, expected: CloudAgentSessionStatus) -> None:
        assert status_logic.session_status_for(task_run_status) == expected

    def test_reasoning_efforts_are_the_values_that_tasks_accepts(self) -> None:
        assert tuple(CloudAgentReasoningEffort.values) == REASONING_EFFORTS
