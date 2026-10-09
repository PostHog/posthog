from __future__ import annotations

from collections.abc import Iterator

import pytest

from posthog.models.scoping import team_scope


@pytest.fixture(autouse=True)
def _cloud_agents_team_scope(request: pytest.FixtureRequest) -> Iterator[None]:
    # The models are fail-closed, so a test built on BaseTest or APIBaseTest runs in the scope of its team.
    instance = getattr(request, "instance", None)
    if instance is None or getattr(instance, "team", None) is None:
        yield
        return
    with team_scope(instance.team.id):
        yield
