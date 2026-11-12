"""Set up AI visibility for a project in one job: its own brand, prompts, keywords and a first run.

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
from collections.abc import Iterable

from django.core.cache import caches
from django.utils import timezone

import structlog

from posthog.hogql.ast import Constant
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.workload import Workload
from posthog.models import Team

from products.aeo.backend import catalog, engine_settings, keyword_suggestions, suggestions
from products.aeo.backend.facade.contracts import (
    MAX_SETUP_WEBSITES,
    SETUP_ENOUGH_KEYWORDS,
    SETUP_ENOUGH_PROMPTS,
    SETUP_KEYWORD_COUNT,
    SETUP_PROMPT_COUNT,
    SETUP_WEBSITE_DAYS,
    BrandCreate,
    BrandCreateError,
    BrandKind,
    BrandStatus,
    BrandUpdate,
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
from products.aeo.backend.models import AEOBrand, AEOCitationCheck, AEOKeyword, AEOPrompt
from products.aeo.backend.seeding import PromptCandidate, upsert_prompts
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
STEPS = (SetupStep.BRAND, SetupStep.PROMPTS, SetupStep.KEYWORDS, SetupStep.FIRST_RUN)


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

    return SetupContext(
        websites=tuple(website_candidates(team)),
        own_domains=tuple(catalog.own_domains(team.id)),
        active_prompts=_active_prompt_count(team.id),
        paused_prompts=AEOPrompt.objects.for_team(team.id).filter(active=False, archived_at__isnull=True).count(),
        keywords=AEOKeyword.objects.for_team(team.id).count(),
        has_checks=AEOCitationCheck.objects.for_team(team.id).exists(),
        ai_data_processing_approved=bool(team.organization.is_ai_data_processing_approved),
        first_run_available=citation_tracking_enabled(team),
        engines=tuple(engine_settings.list_engine_settings(team.id)),
        prompt_target=SETUP_PROMPT_COUNT,
        website_days=SETUP_WEBSITE_DAYS,
    )


def _active_prompt_count(team_id: int) -> int:
    return AEOPrompt.objects.for_team(team_id).filter(active=True, archived_at__isnull=True).count()


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
            {"step": s.step.value, "status": s.status.value, "added": s.added, "detail": s.detail} for s in job.steps
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


class _JobAbandoned(Exception):
    """A reader already marked the job failed, so the task stops instead of writing over that."""


class _Progress:
    """The job's steps as they change, written to the cache after each change so the client sees them move."""

    def __init__(self, team_id: int, job_id: str, started_at: float) -> None:
        self.team_id = team_id
        self.job_id = job_id
        self.started_at = started_at
        self.steps = {step: SetupStepState(step=step, status=SetupStepStatus.PENDING) for step in STEPS}

    def set(self, step: SetupStep, status: SetupStepStatus, *, added: int = 0, detail: str = "") -> None:
        self.steps[step] = SetupStepState(step=step, status=status, added=added, detail=detail)
        self.save(SuggestionJobStatus.PENDING)

    def save(self, status: SuggestionJobStatus, error: str = "") -> None:
        try:
            current, _ = _read(self.team_id, self.job_id)
        except SetupJobNotFoundError:
            raise _JobAbandoned(self.job_id)
        if current.status == SuggestionJobStatus.FAILED:
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


def _add_prompts(team: Team, request: SetupRequest) -> SetupStepState:
    team_id = team.id
    # Paused prompts count too, so a second configure-only setup does not suggest a fresh set on top of them.
    if AEOPrompt.objects.for_team(team_id).filter(archived_at__isnull=True).count() >= SETUP_ENOUGH_PROMPTS:
        return SetupStepState(step=SetupStep.PROMPTS, status=SetupStepStatus.SKIPPED, detail="already_set")
    found = suggestions.suggest_prompts(
        team_id,
        PromptSuggestionRequest(
            domain=request.domain, brand=request.brand, description=request.description, count=SETUP_PROMPT_COUNT
        ),
    )
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
            for item in found
        ],
    )
    return SetupStepState(
        step=SetupStep.PROMPTS,
        status=SetupStepStatus.DONE,
        added=result["created"],
        detail="" if active else "paused",
    )


def _add_keywords(team_id: int, request: SetupRequest) -> SetupStepState:
    from products.aeo.backend.facade.api import create_keywords  # noqa: PLC0415 -- import cycle

    if AEOKeyword.objects.for_team(team_id).count() >= SETUP_ENOUGH_KEYWORDS:
        return SetupStepState(step=SetupStep.KEYWORDS, status=SetupStepStatus.SKIPPED, detail="already_set")
    found = keyword_suggestions.suggest_keywords(
        team_id,
        KeywordSuggestionRequest(
            domain=request.domain, brand=request.brand, description=request.description, count=SETUP_KEYWORD_COUNT
        ),
    )
    result = create_keywords(team_id, [item.keyword for item in found])
    return SetupStepState(step=SetupStep.KEYWORDS, status=SetupStepStatus.DONE, added=result.created)


def _queue_first_run(team: Team, request: SetupRequest) -> SetupStepState:
    from products.aeo.backend.tasks.tasks import (  # noqa: PLC0415 -- import cycle
        citation_tracking_enabled,
        run_aeo_citation_checks_for_team_task,
    )

    def skipped(detail: str) -> SetupStepState:
        return SetupStepState(step=SetupStep.FIRST_RUN, status=SetupStepStatus.SKIPPED, detail=detail)

    if not request.run_first_check and not request.only_first_run:
        return skipped("not_requested")
    if not request.only_first_run and AEOCitationCheck.objects.for_team(team.id).exists():
        return skipped("already_run")
    if not citation_tracking_enabled(team):
        return skipped("not_available")
    if request.only_first_run and request.activate_paused_prompts:
        AEOPrompt.objects.for_team(team.id).filter(active=False, archived_at__isnull=True).update(active=True)
    schedule = engine_settings.engine_schedule(team.id)
    if (
        not catalog.own_domains(team.id)
        or _active_prompt_count(team.id) == 0
        or not (schedule.daily or schedule.weekly)
    ):
        # The run records nothing without an own brand, active prompts and an engine that can run today.
        return skipped("nothing_to_run")
    try:
        # The task holds a per-team lease, so a daily run already in progress makes this one a no-op.
        run_aeo_citation_checks_for_team_task.delay(team.id)
    except Exception:
        logger.exception("aeo_setup_first_run_enqueue_failed", team_id=team.id)
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
    team_id = team.id
    if request.only_first_run:
        for step in (SetupStep.BRAND, SetupStep.PROMPTS, SetupStep.KEYWORDS):
            progress.steps[step] = _not_requested(step)
    else:
        progress.set(SetupStep.BRAND, SetupStepStatus.RUNNING)
        try:
            progress.steps[SetupStep.BRAND] = _ensure_own_brand(team_id, request)
        except BrandCreateError as error:
            progress.steps[SetupStep.BRAND] = SetupStepState(step=SetupStep.BRAND, status=SetupStepStatus.FAILED)
            progress.save(SuggestionJobStatus.FAILED, str(error))
            return

        progress.set(SetupStep.PROMPTS, SetupStepStatus.RUNNING)
        try:
            progress.steps[SetupStep.PROMPTS] = _add_prompts(team, request)
        except PromptSuggestionError as error:
            # Without prompts there is nothing to run, so the job stops here and a retry starts from this step.
            progress.steps[SetupStep.PROMPTS] = SetupStepState(step=SetupStep.PROMPTS, status=SetupStepStatus.FAILED)
            progress.save(SuggestionJobStatus.FAILED, str(error))
            return

        progress.set(SetupStep.KEYWORDS, SetupStepStatus.RUNNING)
        try:
            progress.steps[SetupStep.KEYWORDS] = _add_keywords(team_id, request)
        except (KeywordSuggestionError, KeywordLimitError) as error:
            # Prompts are enough for a first run, so a keyword failure is reported on its step and setup goes on.
            progress.steps[SetupStep.KEYWORDS] = SetupStepState(
                step=SetupStep.KEYWORDS, status=SetupStepStatus.FAILED, detail=str(error)
            )

    progress.set(SetupStep.FIRST_RUN, SetupStepStatus.RUNNING)
    progress.steps[SetupStep.FIRST_RUN] = _queue_first_run(team, request)
    progress.save(SuggestionJobStatus.COMPLETED)
