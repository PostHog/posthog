import time
import threading
from contextlib import nullcontext

import pytest
from unittest.mock import Mock, patch

from django.db import connection
from django.test.utils import CaptureQueriesContext

from celery.exceptions import Retry
from redis.exceptions import (
    ConnectionError as RedisConnectionError,
    LockNotOwnedError,
)

from posthog.models.organization import Organization
from posthog.models.scoping import team_scope
from posthog.models.team import Team
from posthog.redis import get_client

from products.aeo.backend import credits, keyword_suggestions, run_stop
from products.aeo.backend.facade.api import get_prompt_set_overview
from products.aeo.backend.models import AEOCitationCheck, AEOPrompt
from products.aeo.backend.tasks import tasks
from products.aeo.backend.tasks.tasks import (
    recompute_aeo_own_citations_task,
    run_aeo_citation_checks_for_team_task,
    suggest_aeo_keywords_task,
)
from products.aeo.backend.test.factories import ai_credits_used_up, create_citation_check, create_own_brand


@pytest.fixture
def team(db: None) -> Team:
    organization = Organization.objects.create(name="aeo test org", is_ai_data_processing_approved=True)
    return Team.objects.create(organization=organization, name="aeo test team")


def _add_prompt(team: Team, *, active: bool) -> None:
    with team_scope(team.pk):
        AEOPrompt.objects.create(
            team=team, prompt="Q?", prompt_hash="q", prompt_source=AEOPrompt.Source.MANUAL, active=active
        )


@pytest.mark.parametrize(
    "state, kill_switch_on, dispatched, gate_passes",
    [
        ("active_prompts", True, True, True),
        ("only_inactive_prompts", True, False, True),
        ("kill_switch_off", False, False, False),
        ("ai_not_approved", True, False, False),
        ("org_deactivated", True, False, False),
        ("out_of_credits_while_free", True, True, True),
        ("out_of_credits_once_billed", True, False, False),
    ],
)
def test_dispatch_runs_teams_with_active_prompts_that_pass_the_gate(
    team: Team, state: str, kill_switch_on: bool, dispatched: bool, gate_passes: bool
) -> None:
    _add_prompt(team, active=state != "only_inactive_prompts")
    if state == "ai_not_approved":
        Organization.objects.filter(id=team.organization_id).update(is_ai_data_processing_approved=False)
    elif state == "org_deactivated":
        Organization.objects.filter(id=team.organization_id).update(is_active=False)

    billable = frozenset({"ai_visibility"}) if state == "out_of_credits_once_billed" else frozenset()
    with (
        ai_credits_used_up(team) if state.startswith("out_of_credits") else nullcontext(),
        patch.object(credits, "BILLABLE_AI_PRODUCTS", billable),
        patch.object(tasks, "feature_enabled_or_false", return_value=kill_switch_on),
        patch.object(tasks.run_aeo_citation_checks_for_team_task, "delay") as dispatch,
        patch.object(tasks, "run_citation_checks", return_value=(Mock(run_id=None), [])) as run,
    ):
        tasks.run_aeo_citation_checks_task()
        run_aeo_citation_checks_for_team_task(team.id)

    assert [call.args for call in dispatch.call_args_list] == ([(team.id,)] if dispatched else [])
    assert run.call_count == (1 if gate_passes else 0)


def test_setups_run_waits_for_a_run_still_finishing_instead_of_being_dropped(team: Team) -> None:
    lease = get_client().lock(run_stop.lease_key(team.id), timeout=60)
    assert lease.acquire(blocking=False)
    run_stop.mark_run_queued(team.id)

    with (
        patch.object(tasks, "feature_enabled_or_false", return_value=True),
        patch.object(tasks, "run_citation_checks") as run,
        patch.object(run_aeo_citation_checks_for_team_task, "retry", side_effect=Retry()) as retry,
        pytest.raises(Retry),
    ):
        run_aeo_citation_checks_for_team_task(team.id, wait_for_lease=True, queued_at=123.0)

    run.assert_not_called()
    # Each try keeps the time the run was queued, so a stop asked for during the wait still ends it, and the task
    # is allowed every try of the wait rather than Celery's default 3.
    assert retry.call_args.kwargs["kwargs"] == {"wait_for_lease": True, "queued_at": 123.0}
    assert run_aeo_citation_checks_for_team_task.max_retries == tasks.RUN_LEASE_WAIT_RETRIES
    assert run_stop.checks_running(team.id)
    lease.release()
    run_stop.clear_run_queued(team.id)


@pytest.mark.parametrize("run_in_progress", [False, True])
def test_one_run_per_team_at_a_time(team: Team, run_in_progress: bool) -> None:
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


@pytest.mark.parametrize("when", ["before_start", "during_run"])
def test_a_stop_ends_the_run_it_was_asked_for_and_not_a_run_queued_later(team: Team, when: str) -> None:
    def run(_team: Team, stop: threading.Event) -> tuple[Mock, list]:
        if when == "during_run":
            run_stop.request_stop(team.id)
            assert stop.wait(timeout=10), "the run must see the stop"
        return Mock(run_id=None), []

    queued_at = time.time()
    if when == "before_start":
        run_stop.request_stop(team.id)
    with (
        patch.object(tasks, "feature_enabled_or_false", return_value=True),
        patch.object(tasks, "run_citation_checks", side_effect=run) as runner,
    ):
        run_aeo_citation_checks_for_team_task(team.id, queued_at=queued_at)
        assert runner.call_count == (0 if when == "before_start" else 1)
        assert get_client().lock(f"aeo_citation_run:{team.id}", timeout=60).acquire(blocking=False)
        get_client().delete(f"aeo_citation_run:{team.id}")

        # The stop stays for any other run queued before it, and doesn't skip one queued after it.
        assert run_stop.stop_requested(team.id, since=queued_at)
        runner.side_effect = None
        runner.return_value = (Mock(run_id=None), [])
        run_aeo_citation_checks_for_team_task(team.id, queued_at=time.time())
        assert runner.call_count == (1 if when == "before_start" else 2)


def test_a_run_that_outlived_its_lease_still_finishes_cleanly(team: Team) -> None:
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
def test_a_recorded_run_queues_an_own_citation_reconcile_without_failing_on_it(team: Team, enqueue_fails: bool) -> None:
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


def test_refresh_fills_checks_from_before_the_stored_values_and_then_stores_the_views(team: Team) -> None:
    create_own_brand(team, "example.com")
    check_id = create_citation_check(team, "example")

    with (
        patch.object(tasks.recompute_aeo_own_citations_task, "delay", tasks.recompute_aeo_own_citations_task),
        patch.object(
            tasks.refresh_aeo_stored_results_for_team_task, "delay", tasks.refresh_aeo_stored_results_for_team_task
        ),
    ):
        tasks.refresh_aeo_stored_results_for_team_task(team.id)

    assert AEOCitationCheck.objects.for_team(team.id).get(id=check_id).prompt_branded is True
    with CaptureQueriesContext(connection) as queries:
        overview = get_prompt_set_overview(team.id, timezone_name=team.timezone)
    assert overview.current.checks == 1
    assert [q["sql"] for q in queries.captured_queries if "posthog_aeo_citation_check" in q["sql"]] == []


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
def test_sentiment_backlog_pass_scores_each_enabled_team(team: Team, flag_on: bool, expected_starts: int) -> None:
    _add_prompt(team, active=True)

    with (
        patch.object(tasks, "feature_enabled_or_false", return_value=flag_on),
        patch.object(tasks, "start_backlog_sentiment_scoring", side_effect=RuntimeError("temporal down")) as start,
    ):
        tasks.score_aeo_sentiment_backlog_task()

    assert [call.args for call in start.call_args_list] == [(team.id,)] * expected_starts
