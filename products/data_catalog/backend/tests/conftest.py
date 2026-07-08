import pytest

from posthog.models.scoping import team_scope


@pytest.fixture(autouse=True)
def _set_team_scope(request):
    # Only pytest-function-style tests that request the `team` fixture need auto-scoping.
    # unittest-style tests (APIBaseTest/BaseTest) set their own context, so skip them.
    if request.node.get_closest_marker("django_db") is None or "team" not in request.fixturenames:
        yield
        return
    team = request.getfixturevalue("team")
    with team_scope(team.id):
        yield
