import pytest

from posthog.models.scoping import team_scope


@pytest.fixture(autouse=True)
def _set_team_scope(request):
    if request.node.get_closest_marker("django_db") is None:
        yield
        return
    team = request.getfixturevalue("team")
    with team_scope(team.id):
        yield
