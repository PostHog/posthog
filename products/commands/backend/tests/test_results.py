from types import SimpleNamespace
from uuid import UUID, uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase

from parameterized import parameterized

from products.commands.backend.logic.follow_ups import FollowUp, remember, task_run_key
from products.commands.backend.logic.results import stamphog_result
from products.commands.backend.receivers import on_task_run_saved
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
