"""Set up AI visibility for a project in one job: its own brand, prompts and competitors, a first run and keywords.

The job reuses the prompt and keyword suggestion calls and saves what they return, where the review modals
leave the choice to a person. Each step checks what the project already has first, so a second job, or a job
for a project that is half set up, only fills the gaps.

Like the suggestion jobs, the job runs in a Celery task and its state waits in the cache for the client to poll.
The facade and the tasks module import this one, so the steps import them where they run.
"""

from __future__ import annotations

import time
import uuid
import datetime as dt
from collections.abc import Callable, Iterable
from concurrent.futures import Executor, ThreadPoolExecutor

from django.core.cache import caches
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Q
from django.utils import timezone

import structlog
from redis.lock import Lock

from posthog.hogql.ast import Constant
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.workload import Workload
from posthog.models import Team
from posthog.redis import get_client

from products.aeo.backend import catalog, engine_settings, keyword_suggestions, prompt_limit, run_stop, suggestions
from products.aeo.backend.facade.contracts import (
    MAX_SETUP_WEBSITES,
    SETUP_ENOUGH_KEYWORDS,
    SETUP_ENOUGH_PROMPTS,
    SETUP_KEYWORD_COUNT,
    SETUP_PROMPT_COUNT,
    SETUP_PROMPT_COUNT_MAX,
    SETUP_WEBSITE_DAYS,
    BrandCreate,
    BrandCreateError,
    BrandKind,
    BrandStatus,
    BrandUpdate,
    EngineCheckCount,
    KeywordLimitError,
    KeywordSuggestionError,
    KeywordSuggestionRequest,
    PromptOrigin,
    PromptSuggestionError,
    PromptSuggestionRequest,
    SetupAlreadyRunningError,
    SetupContext,
    SetupJob,
    SetupJobNotFoundError,
    SetupRequest,
    SetupStep,
    SetupStepState,
    SetupStepStatus,
    SuggestionJobStatus,
    WebsiteCandidate,
    WebsiteSource,
)
from products.aeo.backend.models import (
    AEOBrand,
    AEOCheckBrand,
    AEOCitationCheck,
    AEOKeyword,
    AEOPrompt,
    AEOPromptVersion,
)
from products.aeo.backend.seeding import PromptCandidate, upsert_prompts
from products.aeo.backend.stored_results import bump_data_version_on_commit
from products.aeo.backend.suggestions import SUGGESTION_CACHE_ALIAS, SUGGESTION_JOB_TTL_SECONDS

logger = structlog.get_logger(__name__)

# Two model calls back to back, each allowed the suggestion task's six minutes, plus the saves.
SETUP_TASK_SOFT_TIME_LIMIT_SECONDS = 13 * 60
SETUP_TASK_TIME_LIMIT_SECONDS = SETUP_TASK_SOFT_TIME_LIMIT_SECONDS + 60
# A job reads as failed this long after it was created. A task that starts later than the start window can no
# longer finish inside it, so it gives up before any paid call.
SETUP_JOB_STALE_SECONDS = 20 * 60
SETUP_START_WINDOW_SECONDS = SETUP_JOB_STALE_SECONDS - SETUP_TASK_TIME_LIMIT_SECONDS
PAGEVIEW_HOSTS_CACHE_SECONDS = 60 * 60
FAILED_ERROR = "Setup failed. Try again in a minute."
STALE_JOB_ERROR = "Setup stopped before it finished. Try again."
# The order the steps run in, which clients show. The first run only needs the prompts, so it is queued before the
# keyword call and its results arrive sooner.
STEPS = (SetupStep.BRAND, SetupStep.RESEARCH, SetupStep.PROMPTS, SetupStep.FIRST_RUN, SetupStep.KEYWORDS)


def _domains(urls: Iterable[str | None]) -> list[str]:
    found: list[str] = []
    for url in urls:
        if not url:
            continue
        raw = url.strip()
        domain = catalog.registrable_domain(raw if "//" in raw else f"//{raw}")
        if domain and domain not in found:
            found.append(domain)
    return found


def _pageview_hosts(team: Team) -> list[tuple[str, int]]:
    # The setup screen reads this on every load, and the answer barely moves within an hour.
    key = f"aeo_setup_pageview_hosts:{team.id}"
    cached = caches[SUGGESTION_CACHE_ALIAS].get(key)
    if isinstance(cached, list):
        return [(str(host), int(pageviews)) for host, pageviews in cached]
    hosts = _query_pageview_hosts(team)
    caches[SUGGESTION_CACHE_ALIAS].set(key, hosts, timeout=PAGEVIEW_HOSTS_CACHE_SECONDS)
    return hosts


def _query_pageview_hosts(team: Team) -> list[tuple[str, int]]:
    query = parse_select(
        "SELECT properties.$host AS host, count() AS pageviews FROM events "
        "WHERE event = '$pageview' AND timestamp >= {since} AND notEmpty(host) "
        "GROUP BY host ORDER BY pageviews DESC LIMIT {limit}",
        placeholders={
            "since": Constant(value=timezone.now() - dt.timedelta(days=SETUP_WEBSITE_DAYS)),
            # Several hosts often share one domain (www, app, docs), so read more hosts than the domains returned.
            "limit": Constant(value=MAX_SETUP_WEBSITES * 4),
        },
    )
    response = execute_hogql_query(
        query=query, team=team, query_type="aeo_setup_pageview_hosts", workload=Workload.ONLINE
    )
    return [(str(host), int(pageviews)) for host, pageviews in response.results or []]


def website_candidates(team: Team) -> list[WebsiteCandidate]:
    """The domains the project may be about, the most likely first: its own brands, the authorized URLs,
    the recording domains, then the hosts with the most pageviews."""
    candidates: list[WebsiteCandidate] = []

    def add(domain: str, source: WebsiteSource, pageviews: int | None = None) -> None:
        if len(candidates) < MAX_SETUP_WEBSITES and all(c.domain != domain for c in candidates):
            candidates.append(WebsiteCandidate(domain=domain, source=source, pageviews=pageviews))

    for domain in catalog.own_domains(team.id):
        add(domain, WebsiteSource.OWN_BRAND)
    for domain in _domains(team.app_urls or []):
        add(domain, WebsiteSource.APP_URLS)
    for domain in _domains(team.recording_domains or []):
        add(domain, WebsiteSource.RECORDING_DOMAINS)
    if len(candidates) < MAX_SETUP_WEBSITES:
        try:
            hosts = _pageview_hosts(team)
        except Exception:
            # The other sources still answer, and the person can type the site.
            logger.warning("aeo_setup_pageview_hosts_failed", team_id=team.id, exc_info=True)
            hosts = []
        pageviews_by_domain: dict[str, int] = {}
        for host, pageviews in hosts:
            for domain in _domains([host]):
                pageviews_by_domain[domain] = pageviews_by_domain.get(domain, 0) + pageviews
        for domain, pageviews in sorted(pageviews_by_domain.items(), key=lambda item: -item[1]):
            add(domain, WebsiteSource.PAGEVIEWS, pageviews)
    return candidates


def read_context(team: Team) -> SetupContext:
    from products.aeo.backend.tasks.tasks import citation_tracking_enabled  # noqa: PLC0415 -- import cycle

    limit = prompt_limit.read(team.id)
    return SetupContext(
        websites=tuple(website_candidates(team)),
        own_domains=tuple(catalog.own_domains(team.id)),
        active_prompts=limit.active_prompts,
        max_active_prompts=limit.max_active_prompts,
        paused_prompts=AEOPrompt.objects.for_team(team.id).filter(active=False, archived_at__isnull=True).count(),
        keywords=AEOKeyword.objects.for_team(team.id).count(),
        has_checks=AEOCitationCheck.objects.for_team(team.id).exists(),
        ai_data_processing_approved=bool(team.organization.is_ai_data_processing_approved),
        first_run_available=citation_tracking_enabled(team),
        engines=tuple(engine_settings.list_engine_settings(team.id)),
        prompt_target=min(SETUP_PROMPT_COUNT, limit.max_active_prompts),
        prompt_count_max=min(SETUP_PROMPT_COUNT_MAX, limit.max_active_prompts),
        website_days=SETUP_WEBSITE_DAYS,
        checks_running=run_stop.checks_running(team.id),
        first_run_checks=tuple(
            EngineCheckCount(engine=row["engine"], checks=row["checks"])
            for row in AEOCitationCheck.objects.for_team(team.id)
            .filter(prompt__active=True, prompt__archived_at__isnull=True)
            .values("engine")
            .annotate(checks=Count("prompt_id", distinct=True))
            .order_by("engine")
        ),
    )


def _job_key(team_id: int, job_id: str) -> str:
    return f"aeo_setup:{team_id}:{job_id}"


def _running_key(team_id: int) -> str:
    return f"aeo_setup_running:{team_id}"


def _store(job: SetupJob, started_at: float) -> dict:
    return {
        "started_at": started_at,
        "status": job.status.value,
        "error": job.error,
        "steps": [
            {
                "step": s.step.value,
                "status": s.status.value,
                "added": s.added,
                "requested": s.requested,
                "detail": s.detail,
            }
            for s in job.steps
        ],
    }


def _save_job(team_id: int, job: SetupJob, *, started_at: float | None = None) -> None:
    cache = caches[SUGGESTION_CACHE_ALIAS]
    if started_at is None:
        stored = cache.get(_job_key(team_id, job.id))
        started_at = stored.get("started_at", time.time()) if isinstance(stored, dict) else time.time()
    cache.set(_job_key(team_id, job.id), _store(job, started_at), timeout=SUGGESTION_JOB_TTL_SECONDS)
    if job.status != SuggestionJobStatus.PENDING and cache.get(_running_key(team_id)) == job.id:
        cache.delete(_running_key(team_id))


def _read(team_id: int, job_id: str) -> tuple[SetupJob, float]:
    stored = caches[SUGGESTION_CACHE_ALIAS].get(_job_key(team_id, job_id))
    if not isinstance(stored, dict):
        raise SetupJobNotFoundError(job_id)
    steps = tuple(
        SetupStepState(
            step=SetupStep(item["step"]),
            status=SetupStepStatus(item["status"]),
            added=item["added"],
            requested=item.get("requested", 0),
            detail=item["detail"],
        )
        for item in stored["steps"]
    )
    job = SetupJob(id=job_id, status=SuggestionJobStatus(stored["status"]), steps=steps, error=stored["error"])
    return job, stored.get("started_at", 0)


def load_job(team_id: int, job_id: str) -> SetupJob:
    job, started_at = _read(team_id, job_id)
    if job.status == SuggestionJobStatus.PENDING and time.time() - started_at > SETUP_JOB_STALE_SECONDS:
        # A hard kill or a lost task never writes a final status.
        job = SetupJob(id=job_id, status=SuggestionJobStatus.FAILED, steps=job.steps, error=STALE_JOB_ERROR)
        _save_job(team_id, job, started_at=started_at)
    return job


def running_job_id(team_id: int) -> str | None:
    """The team's setup job that is still pending, if any."""
    job_id = caches[SUGGESTION_CACHE_ALIAS].get(_running_key(team_id))
    if not job_id:
        return None
    try:
        return job_id if load_job(team_id, job_id).status == SuggestionJobStatus.PENDING else None
    except SetupJobNotFoundError:
        return None


def create_job(team_id: int) -> SetupJob:
    """Raises SetupAlreadyRunningError when the team already has a pending setup job."""
    job = SetupJob(
        id=str(uuid.uuid4()),
        status=SuggestionJobStatus.PENDING,
        steps=tuple(SetupStepState(step=step, status=SetupStepStatus.PENDING) for step in STEPS),
    )
    cache = caches[SUGGESTION_CACHE_ALIAS]
    key = _running_key(team_id)
    # The record goes in before the key, so a request that reads the key mid-claim finds a pending job
    # rather than an empty slot it would take over.
    _save_job(team_id, job, started_at=time.time())
    if not cache.add(key, job.id, timeout=SETUP_JOB_STALE_SECONDS):
        running = running_job_id(team_id)
        if running is not None:
            raise SetupAlreadyRunningError(running)
        # The key pointed at a job that already finished, so this job takes it over. Dropping the key and
        # adding it again, rather than overwriting it, leaves one winner when two requests take over at once.
        cache.delete(key)
        if not cache.add(key, job.id, timeout=SETUP_JOB_STALE_SECONDS):
            raise SetupAlreadyRunningError(running_job_id(team_id) or job.id)
    return job


def fail_job(team_id: int, job_id: str, error: str) -> None:
    try:
        steps = _read(team_id, job_id)[0].steps
    except SetupJobNotFoundError:
        steps = ()
    _save_job(team_id, SetupJob(id=job_id, status=SuggestionJobStatus.FAILED, steps=steps, error=error))


def cancel_job(team_id: int, job_id: str) -> SetupJob:
    with _job_write_lock(team_id, job_id):
        job, _ = _read(team_id, job_id)
        if job.status != SuggestionJobStatus.PENDING:
            # A finished job has nothing to cancel, and a stop now would end the run of a setup started since.
            return job
        steps = tuple(
            SetupStepState(step=step.step, status=SetupStepStatus.SKIPPED, detail="cancelled")
            if step.status in (SetupStepStatus.PENDING, SetupStepStatus.RUNNING)
            else step
            for step in job.steps
        )
        job = SetupJob(id=job_id, status=SuggestionJobStatus.CANCELLED, steps=steps)
        _save_job(team_id, job)
    # The job's first run, queued or still to come, stops too.
    run_stop.request_stop(team_id)
    return job


def _job_write_lock(team_id: int, job_id: str) -> Lock:
    return get_client().lock(f"aeo_setup_job_write:{team_id}:{job_id}", timeout=10, blocking_timeout=10)


class _JobAbandoned(Exception):
    """A reader already marked the job failed, so the task stops instead of writing over that."""


class _Progress:
    """The job's steps as they change, written to the cache after each change so the client sees them move."""

    def __init__(self, team_id: int, job_id: str, started_at: float) -> None:
        self.team_id = team_id
        self.job_id = job_id
        self.started_at = started_at
        self.steps = {step: SetupStepState(step=step, status=SetupStepStatus.PENDING) for step in STEPS}

    def set(self, step: SetupStep, status: SetupStepStatus) -> None:
        self.steps[step] = SetupStepState(step=step, status=status)
        self.save(SuggestionJobStatus.PENDING)

    def checkpoint(self) -> None:
        try:
            current, _ = _read(self.team_id, self.job_id)
        except SetupJobNotFoundError:
            raise _JobAbandoned(self.job_id)
        if current.status != SuggestionJobStatus.PENDING:
            raise _JobAbandoned(self.job_id)

    def save(self, status: SuggestionJobStatus, error: str = "") -> None:
        # Under the job's write lock, so a cancel can't land between the status read and this write and be undone.
        with _job_write_lock(self.team_id, self.job_id):
            try:
                current, _ = _read(self.team_id, self.job_id)
            except SetupJobNotFoundError:
                raise _JobAbandoned(self.job_id)
            if current.status in (SuggestionJobStatus.FAILED, SuggestionJobStatus.CANCELLED):
                raise _JobAbandoned(self.job_id)
            _save_job(
                self.team_id,
                SetupJob(id=self.job_id, status=status, steps=tuple(self.steps[step] for step in STEPS), error=error),
                started_at=self.started_at,
            )


def _ensure_own_brand(team_id: int, request: SetupRequest) -> SetupStepState:
    from products.aeo.backend.facade.api import create_brand, update_brand  # noqa: PLC0415 -- import cycle

    if catalog.own_domains(team_id):
        return SetupStepState(step=SetupStep.BRAND, status=SetupStepStatus.SKIPPED, detail="already_set")
    raw = request.domain.strip()
    domain = catalog.registrable_domain(raw if "//" in raw else f"//{raw}")
    existing = AEOBrand.objects.for_team(team_id).filter(domain=domain).first() if domain else None
    if existing is not None:
        # The site was in the catalog as a competitor, a source or an ignored brand, so setup claims it
        # rather than adding a duplicate. An ignored brand never counts as the team, so it is confirmed too.
        update_brand(
            team_id,
            str(existing.id),
            BrandUpdate(kind=BrandKind.OWN, status=BrandStatus.CONFIRMED, name=request.brand or None),
        )
    else:
        create_brand(team_id, BrandCreate(domain=request.domain, kind=BrandKind.OWN, name=request.brand or None))
    if not catalog.own_domains(team_id):
        raise BrandCreateError(f"{domain or request.domain} could not be set as your brand. Add it in settings.")
    return SetupStepState(step=SetupStep.BRAND, status=SetupStepStatus.DONE, added=1)


def _has_prompts(team_id: int) -> bool:
    # Paused prompts count too, so a second configure-only setup does not suggest a fresh set on top of them.
    return AEOPrompt.objects.for_team(team_id).filter(archived_at__isnull=True).count() >= SETUP_ENOUGH_PROMPTS


def _suggestion_request(request: SetupRequest) -> PromptSuggestionRequest:
    return PromptSuggestionRequest(
        domain=request.domain, brand=request.brand, description=request.description, count=request.prompt_count
    )


def _add_prompts(
    team: Team, request: SetupRequest, research: suggestions.SiteResearch, before_save: Callable[[], None]
) -> SetupStepState:
    team_id = team.id
    found = suggestions.suggest_prompts(team_id, _suggestion_request(request), research=research)
    before_save()
    # Saved before the first run is queued, so the run's answers already resolve to them.
    competitors_added = catalog.add_suggested_competitors(team_id, found.competitors)
    # Without a first run, new prompts are saved paused, so nothing is checked or paid for until someone turns them on.
    active = request.run_first_check
    result = upsert_prompts(
        team,
        [
            PromptCandidate(
                text=item.prompt,
                source=AEOPrompt.Source.IMPORTED,
                topic=item.topic,
                evidence={"via": PromptOrigin.SUGGESTION.value},
                active=active,
            )
            for item in found.prompts
        ],
        fit_to_limit=True,
    )
    if not active:
        detail = "paused"
    elif result["held_back"]:
        detail = "prompt_limit"
    elif result["created"] < request.prompt_count:
        detail = "fewer"
    else:
        detail = ""
    logger.info(
        "aeo_setup_prompts_added",
        team_id=team_id,
        prompts=result["created"],
        requested=request.prompt_count,
        competitors=competitors_added,
    )
    return SetupStepState(
        step=SetupStep.PROMPTS,
        status=SetupStepStatus.DONE,
        added=result["created"],
        requested=request.prompt_count,
        detail=detail,
    )


def _keyword_pool() -> ThreadPoolExecutor:
    return ThreadPoolExecutor(max_workers=1, thread_name_prefix="aeo-setup-keywords")


def _start_keywords(
    team_id: int, request: SetupRequest, description: str, pool: Executor
) -> Callable[[Callable[[], None]], SetupStepState]:
    """Ask for keywords on the pool and return what saves them, so the model call runs while prompts are written.
    Only the call runs on the pool: the reads and the save stay on the task's thread and its database connection."""
    from products.aeo.backend.facade.api import create_keywords  # noqa: PLC0415 -- import cycle

    if AEOKeyword.objects.for_team(team_id).count() >= SETUP_ENOUGH_KEYWORDS:
        return lambda before_save: SetupStepState(
            step=SetupStep.KEYWORDS, status=SetupStepStatus.SKIPPED, detail="already_set"
        )
    keyword_request = KeywordSuggestionRequest(
        domain=request.domain, brand=request.brand, description=description, count=SETUP_KEYWORD_COUNT
    )
    context = keyword_suggestions.read_context(team_id)
    count = keyword_suggestions.suggestion_count(keyword_request.count, len(context.existing_keywords))
    future = (
        pool.submit(keyword_suggestions.generate_keyword_suggestions, team_id, keyword_request, context, count=count)
        if count
        else None
    )

    def finish(before_save: Callable[[], None]) -> SetupStepState:
        if future is None:
            raise KeywordSuggestionError(keyword_suggestions.NO_ROOM_ERROR)
        candidates = future.result()
        # Read the list again, so keywords added while the model worked are neither repeated nor over the cap.
        existing = keyword_suggestions.existing_keywords(team_id)
        room = keyword_suggestions.suggestion_count(keyword_request.count, len(existing))
        found = [candidate for candidate in candidates if candidate.keyword not in existing][:room]
        before_save()
        result = create_keywords(team_id, [item.keyword for item in found])
        return SetupStepState(step=SetupStep.KEYWORDS, status=SetupStepStatus.DONE, added=result.created)

    return finish


def _activate_paused_prompts(team_id: int) -> None:
    with transaction.atomic():
        limit = prompt_limit.lock(team_id)
        paused = AEOPrompt.objects.for_team(team_id).filter(active=False, archived_at__isnull=True)
        fitting = list(paused.order_by("-rank", "created_at", "id").values_list("id", flat=True)[: limit.remaining])
        if fitting:
            paused.filter(id__in=fitting).update(active=True)
            bump_data_version_on_commit(team_id)


def _queue_first_run(team: Team, request: SetupRequest, *, since: float) -> SetupStepState:
    from products.aeo.backend.tasks.tasks import (  # noqa: PLC0415 -- import cycle
        citation_tracking_enabled,
        run_aeo_citation_checks_for_team_task,
    )

    def skipped(detail: str) -> SetupStepState:
        return SetupStepState(step=SetupStep.FIRST_RUN, status=SetupStepStatus.SKIPPED, detail=detail)

    if not request.run_first_check and not request.only_first_run:
        return skipped("not_requested")
    if (
        not request.only_first_run
        and AEOCitationCheck.objects.for_team(team.id)
        .filter(prompt__active=True, prompt__archived_at__isnull=True)
        .exists()
    ):
        return skipped("already_run")
    if not citation_tracking_enabled(team):
        return skipped("not_available")
    if request.only_first_run and request.activate_paused_prompts:
        _activate_paused_prompts(team.id)
    schedule = engine_settings.engine_schedule(team.id)
    if (
        not catalog.own_domains(team.id)
        or prompt_limit.active_prompt_count(team.id) == 0
        or not (schedule.daily or schedule.weekly)
    ):
        # The run records nothing without an own brand, active prompts and an engine that can run today.
        return skipped("nothing_to_run")
    try:
        # The task holds a per-team lease, so a daily run already in progress makes this one a no-op.
        run_stop.mark_run_queued(team.id)
        # The run counts from when setup started, so a stop asked for during setup skips it.
        run_aeo_citation_checks_for_team_task.delay(team.id, wait_for_lease=True, queued_at=since)
    except Exception:
        logger.exception("aeo_setup_first_run_enqueue_failed", team_id=team.id)
        run_stop.clear_run_queued(team.id)
        return SetupStepState(
            step=SetupStep.FIRST_RUN,
            status=SetupStepStatus.FAILED,
            detail="The checks could not be queued. Try again in a minute.",
        )
    return SetupStepState(step=SetupStep.FIRST_RUN, status=SetupStepStatus.DONE)


def _not_requested(step: SetupStep) -> SetupStepState:
    return SetupStepState(step=step, status=SetupStepStatus.SKIPPED, detail="not_requested")


def run_job(team_id: int, job_id: str, request: SetupRequest) -> None:
    # A task that waited in a backed-up queue may start after readers saw the job fail, or too late to finish
    # before they would, so it must not pay for a call.
    try:
        job, started_at = _read(team_id, job_id)
    except SetupJobNotFoundError:
        return
    if job.status != SuggestionJobStatus.PENDING:
        return
    if time.time() - started_at > SETUP_START_WINDOW_SECONDS:
        fail_job(team_id, job_id, STALE_JOB_ERROR)
        return
    team = Team.objects.get(id=team_id)
    progress = _Progress(team_id, job_id, started_at)
    try:
        _run_steps(team, progress, request)
    except _JobAbandoned:
        logger.info("aeo_setup_job_abandoned", team_id=team_id)


def _run_steps(team: Team, progress: _Progress, request: SetupRequest) -> None:
    pool = _keyword_pool()
    try:
        _run_steps_with(team, progress, request, pool)
    finally:
        # A keyword call still running when setup stops is not waited for, and its answer is never saved.
        pool.shutdown(wait=False, cancel_futures=True)


def _run_steps_with(team: Team, progress: _Progress, request: SetupRequest, pool: Executor) -> None:
    team_id = team.id
    description = request.description
    keywords: Callable[[Callable[[], None]], SetupStepState] | None = None
    if request.only_first_run:
        for step in (SetupStep.BRAND, SetupStep.RESEARCH, SetupStep.PROMPTS, SetupStep.KEYWORDS):
            progress.steps[step] = _not_requested(step)
    else:
        progress.set(SetupStep.BRAND, SetupStepStatus.RUNNING)
        try:
            progress.steps[SetupStep.BRAND] = _ensure_own_brand(team_id, request)
        except BrandCreateError as error:
            progress.steps[SetupStep.BRAND] = SetupStepState(step=SetupStep.BRAND, status=SetupStepStatus.FAILED)
            progress.save(SuggestionJobStatus.FAILED, str(error))
            return

        description = request.description
        if _has_prompts(team_id):
            for step in (SetupStep.RESEARCH, SetupStep.PROMPTS):
                progress.steps[step] = SetupStepState(step=step, status=SetupStepStatus.SKIPPED, detail="already_set")
            keywords = _start_keywords(team_id, request, description, pool)
        else:
            progress.set(SetupStep.RESEARCH, SetupStepStatus.RUNNING)
            try:
                research = suggestions.research_site(team_id, _suggestion_request(request))
            except PromptSuggestionError as error:
                progress.steps[SetupStep.RESEARCH] = SetupStepState(
                    step=SetupStep.RESEARCH, status=SetupStepStatus.FAILED
                )
                progress.save(SuggestionJobStatus.FAILED, str(error))
                return
            description = description or research.description
            # Research can take minutes, so a cancel during it stops here, before another paid call starts.
            progress.checkpoint()
            progress.steps[SetupStep.RESEARCH] = SetupStepState(
                step=SetupStep.RESEARCH, status=SetupStepStatus.DONE, added=len(research.competitors)
            )
            progress.steps[SetupStep.KEYWORDS] = SetupStepState(step=SetupStep.KEYWORDS, status=SetupStepStatus.RUNNING)
            keywords = _start_keywords(team_id, request, description, pool)
            progress.set(SetupStep.PROMPTS, SetupStepStatus.RUNNING)
            try:
                progress.steps[SetupStep.PROMPTS] = _add_prompts(team, request, research, progress.checkpoint)
            except PromptSuggestionError as error:
                progress.steps[SetupStep.PROMPTS] = SetupStepState(
                    step=SetupStep.PROMPTS, status=SetupStepStatus.FAILED
                )
                progress.steps[SetupStep.KEYWORDS] = SetupStepState(
                    step=SetupStep.KEYWORDS, status=SetupStepStatus.SKIPPED
                )
                progress.save(SuggestionJobStatus.FAILED, str(error))
                return

    progress.set(SetupStep.FIRST_RUN, SetupStepStatus.RUNNING)
    progress.checkpoint()
    progress.steps[SetupStep.FIRST_RUN] = _queue_first_run(team, request, since=progress.started_at)

    if keywords is not None:
        progress.set(SetupStep.KEYWORDS, SetupStepStatus.RUNNING)
        try:
            progress.steps[SetupStep.KEYWORDS] = keywords(progress.checkpoint)
        except (KeywordSuggestionError, KeywordLimitError) as error:
            # Prompts are enough for a first run, so a keyword failure is reported on its step and setup goes on.
            progress.steps[SetupStep.KEYWORDS] = SetupStepState(
                step=SetupStep.KEYWORDS, status=SetupStepStatus.FAILED, detail=str(error)
            )

    progress.save(SuggestionJobStatus.COMPLETED)


def reset(team_id: int) -> None:
    """Removes what setup saved, so the project can be set up again. Raises SetupAlreadyRunningError while a
    setup job is pending."""
    from products.aeo.backend.facade.api import update_brand  # noqa: PLC0415 -- import cycle

    # Holding a job for the reset keeps a setup from starting, and saving prompts, while the rows are removed.
    job = create_job(team_id)
    try:
        # A check run in flight still writes checks against the current prompts, so it is asked to stop and its
        # prompts are archived rather than deleted.
        checks_running = run_stop.checks_running(team_id)
        if checks_running:
            run_stop.request_stop(team_id)
        now = timezone.now()
        with transaction.atomic():
            current = AEOPrompt.objects.for_team(team_id).filter(archived_at__isnull=True)
            checked = Exists(AEOCitationCheck.objects.for_team(team_id).filter(prompt_id=OuterRef("id")))
            # A version with an author, or a second version, means a person wrote or edited the prompt.
            edited = Exists(
                AEOPromptVersion.objects.for_team(team_id)
                .filter(prompt_id=OuterRef("id"))
                .filter(Q(created_by__isnull=False) | Q(version__gt=1))
            )
            # A prompt with answers or a person's wording is archived, so the answers and the version history with
            # its authors stay. One setup wrote and nobody touched is deleted, because an archived prompt blocks its
            # text from coming back, and setting up the same site again would suggest it.
            keep = current if checks_running else current.filter(checked | edited)
            keep.update(archived_at=now, active=False, updated_at=now)
            if not checks_running:
                current.filter(~checked, ~edited).delete()
            AEOKeyword.objects.for_team(team_id).delete()
            referenced = AEOCheckBrand.objects.for_team(team_id).filter(brand_id=OuterRef("id"))
            AEOBrand.objects.for_team(team_id).filter(status=BrandStatus.SUGGESTED).exclude(kind=BrandKind.OWN).exclude(
                Exists(referenced)
            ).delete()
            setup_brands = (
                AEOBrand.objects.for_team(team_id)
                .filter(Q(kind=BrandKind.OWN) | Q(kind=BrandKind.COMPETITOR, status=BrandStatus.SUGGESTED))
                .values_list("id", flat=True)
            )
            # Inside the transaction, so a brand removed meanwhile rolls the whole reset back.
            for brand_id in list(setup_brands):
                update_brand(team_id, str(brand_id), BrandUpdate(kind=BrandKind.UNKNOWN, status=BrandStatus.SUGGESTED))
        bump_data_version_on_commit(team_id)
    finally:
        _save_job(team_id, SetupJob(id=job.id, status=SuggestionJobStatus.COMPLETED, steps=job.steps))
