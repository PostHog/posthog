import threading

import pytest
from unittest.mock import Mock, patch

from redis.exceptions import (
    ConnectionError as RedisConnectionError,
    LockNotOwnedError,
)

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


def test_a_run_that_outlived_its_lease_still_finishes_cleanly(team: Team, settings) -> None:
    settings.AEO_CITATION_TEAM_IDS = [str(team.id)]

    def expire_lease(*args: object, **kwargs: object) -> None:
        get_client().delete(f"aeo_citation_run:{team.id}")

    with (
        patch.object(tasks, "feature_enabled_or_false", return_value=True),
        patch.object(tasks, "run_citation_checks", side_effect=expire_lease) as run,
    ):
        run_aeo_citation_checks_for_team_task(team.id)

    assert run.call_count == 1


def test_lease_renewal_survives_a_redis_blip_and_stops_the_run_once_the_lease_is_lost(monkeypatch) -> None:
    monkeypatch.setattr(tasks, "RUN_LEASE_RENEW_SECONDS", 0.001)
    lease = Mock()
    lease.reacquire.side_effect = [RedisConnectionError("blip"), None, LockNotOwnedError("gone")]
    lost = threading.Event()

    tasks._renew_lease(lease, threading.Event(), lost, team_id=1)

    assert lease.reacquire.call_count == 3
    assert lost.is_set()
