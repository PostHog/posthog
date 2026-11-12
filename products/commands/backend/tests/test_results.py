from types import SimpleNamespace
from uuid import UUID, uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase

from parameterized import parameterized

from products.commands.backend.logic.follow_ups import FollowUp, docs_check_key, remember, task_run_key
from products.commands.backend.logic.results import stamphog_result
from products.commands.backend.receivers import on_docs_check_finished, on_task_run_saved
from products.knowledge_writer.backend.facade.contracts import IntakeStatus
from products.knowledge_writer.backend.facade.enums import MergeCheckFailure
from products.knowledge_writer.backend.facade.finished_check_hooks import FinishedDocsCheck
from products.stamphog.backend.facade.enums import ReviewRunStatus, ReviewVerdict
from products.stamphog.backend.facade.finished_review_hooks import FinishedReviewRun

FOLLOW_UP = FollowUp(
    address={
        "channel": "slack",
        "integration_id": 1,
        "integration_team_id": 1,
        "slack_channel": "C1",
        "thread_ts": "1",
    },
    subject_label="acme/widgets#7",
    subject_url="https://github.com/acme/widgets/pull/7",
)
DELIVER_FOLLOW_UP = "products.commands.backend.tasks.tasks.deliver_follow_up.delay"


class TestStamphogResult(SimpleTestCase):
    @parameterized.expand(
        [
            ("approved", ReviewRunStatus.COMPLETED, ReviewVerdict.APPROVED, "Stamphog approved"),
            ("refused", ReviewRunStatus.COMPLETED, ReviewVerdict.REFUSED, "Stamphog didn't approve"),
            ("escalated", ReviewRunStatus.COMPLETED, ReviewVerdict.ESCALATE, "wants a person to review"),
            # A gated run stores WAIT, but the gate is the answer, not a wait.
            ("gated", ReviewRunStatus.GATED, ReviewVerdict.WAIT, "can't approve"),
            ("waiting", ReviewRunStatus.COMPLETED, ReviewVerdict.WAIT, "is waiting"),
            # A failed run keeps the verdict it had, which must not read as a decision.
            ("failed", ReviewRunStatus.FAILED, ReviewVerdict.APPROVED, "couldn't finish"),
        ]
    )
    def test_names_the_outcome_the_run_saved(
        self, _name: str, status: ReviewRunStatus, verdict: ReviewVerdict, expected: str
    ) -> None:
        finished = FinishedReviewRun(
            run_id=uuid4(),
            team_id=1,
            repository="acme/widgets",
            pr_number=7,
            status=status,
            verdict=verdict,
            head_sha="abc123",
            author_login="octocat",
            head_branch="feature",
            request_external_review=False,
        )

        assert expected in stamphog_result(finished, FOLLOW_UP)


class TestQaResult(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()

    def _run(self, run_id: UUID, status: str, *, is_terminal: bool, state: dict | None = None) -> SimpleNamespace:
        return SimpleNamespace(
            id=run_id, team_id=self.team.id, task_id=uuid4(), status=status, is_terminal=is_terminal, state=state
        )

    def test_a_qa_run_reports_once_when_it_ends(self) -> None:
        run_id = uuid4()
        remember(task_run_key(str(run_id)), FOLLOW_UP)
        # The task run API lets the run's owner write its state, so an address there must not count.
        planted = self._run(
            uuid4(), "completed", is_terminal=True, state={"commands_follow_up": FOLLOW_UP.to_payload()}
        )

        with patch(DELIVER_FOLLOW_UP) as deliver, self.captureOnCommitCallbacks(execute=True):
            on_task_run_saved(type(None), self._run(run_id, "in_progress", is_terminal=False), created=False)
            on_task_run_saved(type(None), planted, created=False, update_fields=["status"])
            # A terminal run can be saved again, for example with its output.
            finished = self._run(run_id, "completed", is_terminal=True)
            on_task_run_saved(type(None), finished, created=False, update_fields=["status"])
            on_task_run_saved(type(None), finished, created=False, update_fields=None)

        deliver.assert_called_once()
        assert deliver.call_args.kwargs["address"]["thread_ts"] == "1"
        assert "finished" in deliver.call_args.kwargs["message"]


class TestDocsCheckResult(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()

    @parameterized.expand(
        [
            ("no_docs", "no_docs", None, None, "found nothing in [acme/widgets#7]"),
            (
                "joined",
                "joined",
                None,
                "https://github.com/PostHog/posthog.com/pull/9",
                "[its docs pull request](https://github.com/PostHog/posthog.com/pull/9)",
            ),
            ("check_failed", "no_docs", MergeCheckFailure.RETRIES_EXHAUSTED, None, "Try `docs` again"),
            ("writer_not_set_up", "no_docs", MergeCheckFailure.NO_DOCS_GITHUB, None, "isn't fully set up"),
            ("check_capped", "no_docs", MergeCheckFailure.CHECK_CAPPED, None, "hit its docs check limit"),
        ]
    )
    def test_a_docs_check_reports_once_when_it_ends(
        self,
        _name: str,
        status: IntakeStatus,
        failure_reason: MergeCheckFailure | None,
        pull_request_url: str | None,
        expected: str,
    ) -> None:
        remember(docs_check_key("waiter-1"), FOLLOW_UP)
        finished = FinishedDocsCheck(
            waiter_ids=("waiter-1",), status=status, failure_reason=failure_reason, pull_request_url=pull_request_url
        )

        with patch(DELIVER_FOLLOW_UP) as deliver:
            on_docs_check_finished(finished)
            on_docs_check_finished(finished)

        deliver.assert_called_once()
        assert deliver.call_args.kwargs["address"]["thread_ts"] == "1"
        assert expected in deliver.call_args.kwargs["message"]

    def test_a_failed_delivery_still_tells_the_waiters_after_it(self) -> None:
        for waiter_id in ("first-waiter", "second-waiter"):
            remember(docs_check_key(waiter_id), FOLLOW_UP)
        finished = FinishedDocsCheck(
            waiter_ids=("first-waiter", "second-waiter"), status="no_docs", failure_reason=None, pull_request_url=None
        )

        with patch(DELIVER_FOLLOW_UP, side_effect=[ConnectionError("broker is down"), None]) as deliver:
            on_docs_check_finished(finished)

        assert deliver.call_count == 2
