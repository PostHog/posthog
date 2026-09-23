from contextlib import ExitStack

from posthog.models.scoping import team_scope


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
