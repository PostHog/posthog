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

from products.aeo.backend import keyword_suggestions
from products.aeo.backend.tasks import tasks
from products.aeo.backend.tasks.tasks import (
    recompute_aeo_own_citations_task,
    run_aeo_citation_checks_for_team_task,
    suggest_aeo_keywords_task,
)


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
        patch.object(tasks, "run_citation_checks", return_value=(Mock(run_id=None), [])) as run,
    ):
        run_aeo_citation_checks_for_team_task(team.id)

    assert run.call_count == (0 if run_in_progress else 1)
    if not run_in_progress:
        assert lease.acquire(blocking=False), "the finished run must give the lease back"
    lease.release()


def test_a_run_that_outlived_its_lease_still_finishes_cleanly(team: Team, settings) -> None:
    settings.AEO_CITATION_TEAM_IDS = [str(team.id)]

    def expire_lease(*args: object, **kwargs: object) -> tuple[Mock, list]:
        get_client().delete(f"aeo_citation_run:{team.id}")
        return Mock(run_id=None), []

    with (
        patch.object(tasks, "feature_enabled_or_false", return_value=True),
        patch.object(tasks, "run_citation_checks", side_effect=expire_lease) as run,
    ):
        run_aeo_citation_checks_for_team_task(team.id)

    assert run.call_count == 1


@pytest.mark.parametrize("enqueue_fails", [False, True])
def test_a_recorded_run_queues_an_own_citation_reconcile_without_failing_on_it(
    team: Team, settings, enqueue_fails: bool
) -> None:
    settings.AEO_CITATION_TEAM_IDS = [str(team.id)]

    with (
        patch.object(tasks, "feature_enabled_or_false", return_value=True),
        patch.object(tasks, "run_citation_checks", return_value=(Mock(run_id="run-1"), [])),
        patch.object(tasks, "sync_brands_from_run", return_value=Mock(domains=0, created=0)),
        patch.object(tasks, "recompute_aeo_own_citations_task") as reconcile,
    ):
        if enqueue_fails:
            reconcile.delay.side_effect = ConnectionError("broker unavailable")
        run_aeo_citation_checks_for_team_task(team.id)

    reconcile.delay.assert_called_once_with(team.id)


def test_a_recompute_retries_while_another_one_holds_the_team(team: Team) -> None:
    held = get_client().lock(f"aeo_own_citations_recompute:{team.id}", timeout=60)
    assert held.acquire(blocking=False)

    with (
        patch.object(tasks, "recompute_own_citations") as recompute,
        pytest.raises(tasks.RecomputeAlreadyRunning),
    ):
        recompute_aeo_own_citations_task(team.id)

    recompute.assert_not_called()
    held.release()


def test_lease_renewal_survives_a_redis_blip_and_stops_the_run_once_the_lease_is_lost(monkeypatch) -> None:
    monkeypatch.setattr(tasks, "RUN_LEASE_RENEW_SECONDS", 0.001)
    lease = Mock()
    lease.reacquire.side_effect = [RedisConnectionError("blip"), None, LockNotOwnedError("gone")]
    lost = threading.Event()

    tasks._renew_lease(lease, threading.Event(), lost, team_id=1)

    assert lease.reacquire.call_count == 3
    assert lost.is_set()


def test_keyword_suggestion_task_fails_the_job_when_it_crashes(team: Team) -> None:
    job = keyword_suggestions.create_job(team.id)

    with (
        patch.object(keyword_suggestions, "resolve_ai_gateway_config", side_effect=RuntimeError("boom")),
        pytest.raises(RuntimeError),
    ):
        suggest_aeo_keywords_task(
            team.id, job.id, {"domain": "example.com", "brand": "", "description": "", "count": 5}
        )

    failed = keyword_suggestions.load_job(team.id, job.id)
    assert (failed.status, failed.error) == ("failed", keyword_suggestions.FAILED_ERROR)


@pytest.mark.parametrize("job_state", ["failed", "missing"])
def test_keyword_suggestion_task_skips_a_job_that_is_no_longer_pending(team: Team, job_state: str) -> None:
    job_id = (
        keyword_suggestions.create_job(team.id).id if job_state == "failed" else "00000000-0000-4000-8000-000000000000"
    )
    if job_state == "failed":
        keyword_suggestions.fail_job(team.id, job_id, keyword_suggestions.STALE_JOB_ERROR)

    with patch.object(keyword_suggestions, "resolve_ai_gateway_config") as gateway:
        suggest_aeo_keywords_task(
            team.id, job_id, {"domain": "example.com", "brand": "", "description": "", "count": 5}
        )

    gateway.assert_not_called()
    if job_state == "failed":
        assert keyword_suggestions.load_job(team.id, job_id).error == keyword_suggestions.STALE_JOB_ERROR


@pytest.mark.parametrize("flag_on, expected_starts", [(True, 1), (False, 0)], ids=["enabled", "flag_off"])
def test_sentiment_backlog_pass_scores_each_enabled_team(
    team: Team, settings, flag_on: bool, expected_starts: int
) -> None:
    settings.AEO_CITATION_TEAM_IDS = [str(team.id), "not-a-team"]

    with (
        patch.object(tasks, "feature_enabled_or_false", return_value=flag_on),
        patch.object(tasks, "start_backlog_sentiment_scoring", side_effect=RuntimeError("temporal down")) as start,
    ):
        tasks.score_aeo_sentiment_backlog_task()

    assert [call.args for call in start.call_args_list] == [(team.id,)] * expected_starts
