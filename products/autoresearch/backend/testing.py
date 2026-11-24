from collections.abc import Iterable, Iterator
from contextlib import ExitStack, contextmanager
from datetime import datetime
from uuid import UUID, uuid4

from unittest.mock import patch

from posthog.models.scoping import team_scope

from products.tasks.backend.facade.contracts import TaskRunSpend


class TeamScopedTestMixin:
    """Runs each test inside its team's scope.

    The models are fail-closed, so a test that builds fixtures or calls a service
    function directly has to set the scope that a request, a Temporal activity, or a
    management command sets in production.
    """

    def setUp(self) -> None:
        super().setUp()  # type: ignore[misc]
        stack = ExitStack()
        stack.enter_context(team_scope(self.team.id))  # type: ignore[attr-defined]
        self.addCleanup(stack.close)  # type: ignore[attr-defined]


@contextmanager
def fake_task_run_spend(runs: dict[UUID, tuple[datetime, int | None, int]]) -> Iterator[None]:
    """Stands in for the Tasks readers the monthly training budget calls.

    ``runs`` maps a task run id to when it started, its token cost and its compute cost, in micro-USD.
    Like the real readers, a run started before ``since`` is not listed, and an unknown id has no spend.
    """

    def _run_ids(*, team_id: int, origin_product: str, since: datetime) -> list[UUID]:
        return [run_id for run_id, (created_at, _, _) in runs.items() if created_at >= since]

    def _spend(*, team_id: int, run_ids: Iterable[UUID]) -> list[TaskRunSpend]:
        return [
            TaskRunSpend(
                created_at=runs[run_id][0],
                run_id=run_id,
                task_id=uuid4(),
                cost_microusd=runs[run_id][1],
                complete=True,
                is_terminal=True,
                stage="task",
                accounting_failed=False,
                compute_cost_microusd=runs[run_id][2],
            )
            for run_id in run_ids
            if run_id in runs
        ]

    with (
        patch("products.autoresearch.backend.limits.origin_run_ids_since", side_effect=_run_ids),
        patch("products.autoresearch.backend.limits.get_task_runs_spend", side_effect=_spend),
    ):
        yield
