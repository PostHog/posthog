from collections.abc import Callable, Iterable
from contextlib import ExitStack
from datetime import UTC, datetime
from uuid import UUID, uuid4

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


def fake_task_runs_spend(costs: dict[UUID, tuple[int | None, int]]) -> Callable[..., list[TaskRunSpend]]:
    """A stand-in for the Tasks spend reader, keyed by task run id: (token cost, compute cost) in micro-USD.

    Like the real reader, it returns nothing for an id it does not know.
    """

    def _spend(*, team_id: int, run_ids: Iterable[UUID]) -> list[TaskRunSpend]:
        return [
            TaskRunSpend(
                created_at=datetime.now(UTC),
                run_id=run_id,
                task_id=uuid4(),
                cost_microusd=costs[run_id][0],
                complete=True,
                is_terminal=True,
                stage="task",
                accounting_failed=False,
                compute_cost_microusd=costs[run_id][1],
            )
            for run_id in run_ids
            if run_id in costs
        ]

    return _spend
