"""Shared test helpers for the Deployments backend.

`DeploymentsTeamScopedTestMixin` wraps `setUp` / `tearDown` with a
`team_scope` context using `self.team.id`, so queries through
`ProductTeamModel.objects` find a team and don't raise `TeamScopeError`.

Mirrors the pattern at
`products/visual_review/backend/tests/conftest.py:57-89`.
"""

from __future__ import annotations

from contextlib import AbstractContextManager

from posthog.models.scoping import team_scope


class DeploymentsTeamScopedTestMixin:
    """Wraps setUp/tearDown with team_scope(self.team.id).

    Place BEFORE `APIBaseTest` / `BaseTest` in the MRO so its setUp runs
    first (creating `self.team`) and ours can use it. The `_cm` is
    initialised to None up front so a partial-init failure in setUp
    doesn't leave tearDown calling __exit__ on an unentered ctx manager.
    """

    _cm: AbstractContextManager[None] | None = None

    def setUp(self) -> None:
        super().setUp()  # type: ignore[misc]
        cm = team_scope(self.team.id)  # type: ignore[attr-defined]
        cm.__enter__()
        self._cm = cm

    def tearDown(self) -> None:
        if self._cm is not None:
            try:
                self._cm.__exit__(None, None, None)
            finally:
                self._cm = None
        super().tearDown()  # type: ignore[misc]
