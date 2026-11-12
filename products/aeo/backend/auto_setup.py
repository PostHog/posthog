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
    BrandUpdate,
    KeywordLimitError,
    KeywordSuggestionError,
    KeywordSuggestionRequest,
    PromptImport,
    PromptOrigin,
    PromptSuggestionError,
    PromptSuggestionRequest,
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
from products.aeo.backend.suggestions import SUGGESTION_CACHE_ALIAS, SUGGESTION_JOB_TTL_SECONDS

logger = structlog.get_logger(__name__)

# Two model calls back to back, each allowed the suggestion task's six minutes, plus the saves.
SETUP_JOB_STALE_SECONDS = 16 * 60
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
        keywords=AEOKeyword.objects.for_team(team.id).count(),
        has_checks=AEOCitationCheck.objects.for_team(team.id).exists(),
        ai_data_processing_approved=bool(team.organization.is_ai_data_processing_approved),
        first_run_available=citation_tracking_enabled(team),
        engines=tuple(engine_settings.list_engine_settings(team.id)),
        prompt_target=SETUP_PROMPT_COUNT,
    )


def _active_prompt_count(team_id: int) -> int:
    return AEOPrompt.objects.for_team(team_id).filter(active=True, archived_at__isnull=True).count()


def _job_key(team_id: int, job_id: str) -> str:
    return f"aeo_setup:{team_id}:{job_id}"


def _save_job(team_id: int, job: SetupJob, *, started_at: float | None = None) -> None:
    if started_at is None:
        stored = caches[SUGGESTION_CACHE_ALIAS].get(_job_key(team_id, job.id))
        started_at = stored.get("started_at", time.time()) if isinstance(stored, dict) else time.time()
    caches[SUGGESTION_CACHE_ALIAS].set(
        _job_key(team_id, job.id),
        {
            "started_at": started_at,
            "status": job.status.value,
            "error": job.error,
            "steps": [
                {"step": s.step.value, "status": s.status.value, "added": s.added, "detail": s.detail}
                for s in job.steps
            ],
        },
        timeout=SUGGESTION_JOB_TTL_SECONDS,
    )


def load_job(team_id: int, job_id: str) -> SetupJob:
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
    started_at = stored.get("started_at", 0)
    if stored["status"] == SuggestionJobStatus.PENDING and time.time() - started_at > SETUP_JOB_STALE_SECONDS:
        # A hard kill or a lost task never writes a final status.
        job = SetupJob(id=job_id, status=SuggestionJobStatus.FAILED, steps=steps, error=STALE_JOB_ERROR)
        _save_job(team_id, job, started_at=started_at)
        return job
    return SetupJob(id=job_id, status=SuggestionJobStatus(stored["status"]), steps=steps, error=stored["error"])


def create_job(team_id: int) -> SetupJob:
    job = SetupJob(
        id=str(uuid.uuid4()),
        status=SuggestionJobStatus.PENDING,
        steps=tuple(SetupStepState(step=step, status=SetupStepStatus.PENDING) for step in STEPS),
    )
    _save_job(team_id, job, started_at=time.time())
    return job


def fail_job(team_id: int, job_id: str, error: str) -> None:
    try:
        steps = load_job(team_id, job_id).steps
    except SetupJobNotFoundError:
        steps = ()
    _save_job(team_id, SetupJob(id=job_id, status=SuggestionJobStatus.FAILED, steps=steps, error=error))


class _Progress:
    """The job's steps as they change, written to the cache after each change so the client sees them move."""

    def __init__(self, team_id: int, job_id: str) -> None:
        self.team_id = team_id
        self.job_id = job_id
        self.steps = {step: SetupStepState(step=step, status=SetupStepStatus.PENDING) for step in STEPS}

    def set(self, step: SetupStep, status: SetupStepStatus, *, added: int = 0, detail: str = "") -> None:
        self.steps[step] = SetupStepState(step=step, status=status, added=added, detail=detail)
        self.save(SuggestionJobStatus.PENDING)

    def save(self, status: SuggestionJobStatus, error: str = "") -> None:
        _save_job(
            self.team_id,
            SetupJob(id=self.job_id, status=status, steps=tuple(self.steps[step] for step in STEPS), error=error),
        )


def _ensure_own_brand(team_id: int, request: SetupRequest) -> SetupStepState:
    from products.aeo.backend.facade.api import create_brand, update_brand  # noqa: PLC0415 -- import cycle

    if catalog.own_domains(team_id):
        return SetupStepState(step=SetupStep.BRAND, status=SetupStepStatus.SKIPPED, detail="already_set")
    raw = request.domain.strip()
    domain = catalog.registrable_domain(raw if "//" in raw else f"//{raw}")
    existing = AEOBrand.objects.for_team(team_id).filter(domain=domain).first() if domain else None
    if existing is not None:
        # The site was in the catalog as a competitor or a source, so setup claims it rather than adding a duplicate.
        update_brand(team_id, str(existing.id), BrandUpdate(kind=BrandKind.OWN, name=request.brand or None))
    else:
        create_brand(team_id, BrandCreate(domain=request.domain, kind=BrandKind.OWN, name=request.brand or None))
    return SetupStepState(step=SetupStep.BRAND, status=SetupStepStatus.DONE, added=1)


def _add_prompts(team_id: int, request: SetupRequest) -> SetupStepState:
    from products.aeo.backend.facade.api import import_prompts  # noqa: PLC0415 -- import cycle

    if _active_prompt_count(team_id) >= SETUP_ENOUGH_PROMPTS:
        return SetupStepState(step=SetupStep.PROMPTS, status=SetupStepStatus.SKIPPED, detail="already_set")
    found = suggestions.suggest_prompts(
        team_id,
        PromptSuggestionRequest(
            domain=request.domain, brand=request.brand, description=request.description, count=SETUP_PROMPT_COUNT
        ),
    )
    result = import_prompts(
        team_id,
        [PromptImport(prompt=item.prompt, topic=item.topic, origin=PromptOrigin.SUGGESTION) for item in found],
    )
    return SetupStepState(step=SetupStep.PROMPTS, status=SetupStepStatus.DONE, added=result.created)


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

    if not request.run_first_check:
        return SetupStepState(step=SetupStep.FIRST_RUN, status=SetupStepStatus.SKIPPED, detail="not_requested")
    if AEOCitationCheck.objects.for_team(team.id).exists():
        return SetupStepState(step=SetupStep.FIRST_RUN, status=SetupStepStatus.SKIPPED, detail="already_run")
    if not citation_tracking_enabled(team):
        return SetupStepState(step=SetupStep.FIRST_RUN, status=SetupStepStatus.SKIPPED, detail="not_available")
    # The task holds a per-team lease, so a daily run already in progress makes this one a no-op.
    run_aeo_citation_checks_for_team_task.delay(team.id)
    return SetupStepState(step=SetupStep.FIRST_RUN, status=SetupStepStatus.DONE)


def run_job(team_id: int, job_id: str, request: SetupRequest) -> None:
    # A task that waited in a backed-up queue may start after readers saw the job fail, so it must not pay for a call.
    try:
        if load_job(team_id, job_id).status != SuggestionJobStatus.PENDING:
            return
    except SetupJobNotFoundError:
        return
    team = Team.objects.get(id=team_id)
    progress = _Progress(team_id, job_id)

    progress.set(SetupStep.BRAND, SetupStepStatus.RUNNING)
    try:
        progress.steps[SetupStep.BRAND] = _ensure_own_brand(team_id, request)
    except BrandCreateError as error:
        progress.steps[SetupStep.BRAND] = SetupStepState(step=SetupStep.BRAND, status=SetupStepStatus.FAILED)
        progress.save(SuggestionJobStatus.FAILED, str(error))
        return

    progress.set(SetupStep.PROMPTS, SetupStepStatus.RUNNING)
    try:
        progress.steps[SetupStep.PROMPTS] = _add_prompts(team_id, request)
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
