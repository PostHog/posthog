import pytest
from unittest.mock import patch

from posthog.models.organization import Organization
from posthog.models.team import Team
from posthog.redis import get_client

from products.aeo.backend.tasks import tasks
from products.aeo.backend.tasks.tasks import run_aeo_citation_checks_for_team_task


@pytest.fixture
def team(db: None) -> Team:
    organization = Organization.objects.create(name="aeo test org")
    return Team.objects.create(organization=organization, name="aeo test team")


@pytest.mark.parametrize("run_in_progress", [False, True])
def test_one_run_per_team_at_a_time(team: Team, settings, run_in_progress: bool) -> None:
    settings.AEO_CITATION_TEAM_IDS = [str(team.id)]
    lease = get_client().lock(f"aeo_citation_run:{team.id}", timeout=60)
    if run_in_progress:
        assert lease.acquire(blocking=False)

    with (
        patch.object(tasks, "feature_enabled_or_false", return_value=True),
        patch.object(tasks, "run_citation_checks") as run,
    ):
        run_aeo_citation_checks_for_team_task(team.id)

    assert run.call_count == (0 if run_in_progress else 1)
    if not run_in_progress:
        assert lease.acquire(blocking=False), "the finished run must give the lease back"
    lease.release()
