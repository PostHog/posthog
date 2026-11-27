"""Scores brand sentiment for one citation run.

The ONNX sentiment model and its dependencies are only in the LLM analytics image,
which the AEO Temporal queue's worker runs, so the runner cannot classify inline: it starts this
workflow, and the activity reads the run's answers back from Postgres, scores the
sentences that name the brand, and writes the label and score to the check rows.
With time left, it scores the sentences that name each other catalog brand the same way,
and writes those labels to the answer's brand rows.
"""

from __future__ import annotations

import time
import uuid
import asyncio
import datetime as dt
import dataclasses
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

import structlog
from temporalio import activity, workflow
from temporalio.common import RetryPolicy, WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.client import sync_connect
from posthog.temporal.common.utils import close_db_connections

from products.aeo.backend.brand import brand_regex
from products.aeo.backend.catalog import own_domains
from products.aeo.backend.engines import own_domains_key
from products.aeo.backend.facade.contracts import BrandKind
from products.aeo.backend.models import AEOCheckBrand, AEOCitationCheck
from products.aeo.backend.sentiment import (
    UNSCORABLE,
    AnswerSentiment,
    BrandSentence,
    MentionSpan,
    SentenceSentiment,
    aggregate_sentiment,
    brand_sentences,
    mention_sentences,
    sentence_sentiment,
)
from products.aeo.backend.stored_results import bump_data_version_on_commit

if TYPE_CHECKING:
    from posthog.temporal.common.registration import ActivityDefinition

logger = structlog.get_logger(__name__)

WORKFLOW_NAME = "aeo-brand-sentiment"
CLASSIFY_TIMEOUT = dt.timedelta(minutes=15)
# Stops starting new answers well inside the timeout, so the last one still has time to finish.
SCORING_BUDGET = dt.timedelta(minutes=10)
# Each answer's score is saved as soon as it is classified, so progress shows up while a pass runs.
ANSWERS_PER_WRITE = 1
CLASSIFY_BATCH = 32
# Brand rows are short, a few sentences each, so they are saved in larger groups.
BRANDS_PER_WRITE = 20
# Answers scored before the setting was turned on, or missed by a failed run, are picked up from
# this far back, which matches the window the prompt report shows.
BACKLOG_WINDOW = dt.timedelta(days=30)
MAX_ROWS_PER_RUN = 2000


@dataclasses.dataclass(frozen=True)
class AEOBrandSentimentInputs:
    team_id: int
    # None scores only the backlog, for passes that no citation run started.
    run_id: str | None = None


@dataclasses.dataclass(frozen=True)
class _PendingAnswer:
    check_id: str
    sentences: list[BrandSentence]


@dataclasses.dataclass(frozen=True)
class _PendingBrand:
    """One brand row of an answer, with the sentences that name that brand."""

    check_brand_id: str
    sentences: list[BrandSentence]


@dataclasses.dataclass(frozen=True)
class _ScoredAnswer:
    check_id: str
    sentiment: AnswerSentiment
    sentences: list[SentenceSentiment]


@dataclasses.dataclass(frozen=True)
class _PendingBatch:
    answers: list[_PendingAnswer]
    # The own domains the sentences were picked for. A score is written only while a check still carries it.
    own_domains_key: str


def _load_pending(inputs: AEOBrandSentimentInputs) -> _PendingBatch:
    """The run's unscored answers, then the team's other unscored answers from the backlog window,
    oldest first, capped so one activity never scans an unbounded history.

    Only answers that name the brand count toward the cap: an answer without a mention stays NULL
    forever, so letting it fill the slice would starve newer answers that can be scored.

    Two concurrent runs can both pick up the same backlog row. The writes are idempotent (the same
    text scores the same), so that only costs a duplicate classification, and no transaction is
    held across the model call that a row lock could ride on."""
    target_domains = own_domains(inputs.team_id)
    key = own_domains_key(target_domains)
    regex = brand_regex(target_domains)
    if regex is None:
        return _PendingBatch(answers=[], own_domains_key=key)
    # A check with another key waits for the own-citation reconcile, which clears what it scored before.
    # A check that has a label but no sentences was scored before the sentences were stored, so it
    # is scored again to fill them in.
    unscored = AEOCitationCheck.objects.for_team(inputs.team_id).filter(
        Q(brand_sentiment__isnull=True) | Q(brand_sentiment_sentences__isnull=True),
        check_failed=False,
        own_domains_key=key,
        answer_text__iregex=regex,
    )
    own_rows: list[tuple[uuid.UUID, str | None]] = []
    backlog = unscored
    if inputs.run_id:
        own_rows = list(unscored.filter(run_id=inputs.run_id).order_by("created_at").values_list("id", "answer_text"))
        backlog = unscored.exclude(run_id=inputs.run_id)
    backlog_rows = list(
        backlog.filter(created_at__gte=timezone.now() - BACKLOG_WINDOW)
        .order_by("created_at")
        .values_list("id", "answer_text")[: max(0, MAX_ROWS_PER_RUN - len(own_rows))]
    )
    pending = [
        _PendingAnswer(check_id=str(check_id), sentences=brand_sentences(text, target_domains))
        for check_id, text in [*own_rows, *backlog_rows]
    ]
    return _PendingBatch(answers=[answer for answer in pending if answer.sentences], own_domains_key=key)


def _write_scores(team_id: int, own_domains_key: str, scored: Sequence[_ScoredAnswer]) -> int:
    """Write the scores of the checks that still carry the key they were picked with, and return how many.

    The own domains can change while the model runs. The row locks order this write against the
    reconcile, which re-keys a check and clears its score in one update."""
    checks = AEOCitationCheck.objects.for_team(team_id)
    with transaction.atomic():
        current = {
            str(check_id)
            for check_id in checks.select_for_update()
            .filter(id__in=[answer.check_id for answer in scored], own_domains_key=own_domains_key)
            .values_list("id", flat=True)
        }
        rows = [
            AEOCitationCheck(
                id=answer.check_id,
                brand_sentiment=answer.sentiment.label,
                brand_sentiment_score=answer.sentiment.score,
                brand_sentiment_sentences=[dataclasses.asdict(sentence) for sentence in answer.sentences],
            )
            for answer in scored
            if answer.check_id in current
        ]
        checks.bulk_update(rows, ["brand_sentiment", "brand_sentiment_score", "brand_sentiment_sentences"])
        bump_data_version_on_commit(team_id)
    return len(rows)


@dataclasses.dataclass(frozen=True)
class _PendingBrands:
    brands: list[_PendingBrand]
    # Rows whose mentions no sentence of the answer holds. They are marked, so the next pass moves past them.
    unscorable: list[str]


def _mention_spans(answer_text: str, mentions: list[dict[str, Any]]) -> list[MentionSpan]:
    """The mentions the row stored, as spans of the answer. A span whose text no longer reads as the stored
    surface is left out, so a sentence is never picked for a mention it does not hold."""
    spans: list[MentionSpan] = []
    for mention in mentions:
        start, surface = mention.get("start"), mention.get("surface")
        if isinstance(start, int) and surface and answer_text[start : start + len(surface)] == surface:
            spans.append(MentionSpan(start=start, end=start + len(surface)))
    return spans


def _load_pending_brands(team_id: int) -> _PendingBrands:
    """The recent brand rows that name a brand other than the own one and have no score yet, oldest first,
    capped like the answers. The own brand's sentiment is on the check, so its rows are skipped. The sentences
    are the ones that hold the mentions the row stored, by their offsets, so a name with punctuation such as
    `Dr. Martens` stays whole."""
    rows = list(
        AEOCheckBrand.objects.for_team(team_id)
        .filter(created_at__gte=timezone.now() - BACKLOG_WINDOW, mentioned=True, sentiment__isnull=True)
        .exclude(mentions=[])
        .exclude(brand__kind=BrandKind.OWN)
        .order_by("created_at", "id")
        .values_list("id", "citation_check_id", "mentions")[:MAX_ROWS_PER_RUN]
    )
    texts = dict(
        AEOCitationCheck.objects.for_team(team_id)
        .filter(id__in={check_id for _, check_id, _ in rows}, check_failed=False)
        .values_list("id", "answer_text")
    )
    brands: list[_PendingBrand] = []
    unscorable: list[str] = []
    for row_id, check_id, mentions in rows:
        text = texts.get(check_id) or ""
        sentences = mention_sentences(text, _mention_spans(text, mentions))
        if sentences:
            brands.append(_PendingBrand(check_brand_id=str(row_id), sentences=sentences))
        else:
            unscorable.append(str(row_id))
    return _PendingBrands(brands=brands, unscorable=unscorable)


def _mark_unscorable(team_id: int, row_ids: list[str]) -> int:
    return (
        AEOCheckBrand.objects.for_team(team_id)
        .filter(id__in=row_ids, sentiment__isnull=True)
        .update(sentiment=UNSCORABLE)
    )


def _write_brand_scores(team_id: int, scored: Mapping[str, AnswerSentiment]) -> int:
    """Write the scores of brand rows. A row that a re-resolve replaced while the model ran is gone, so
    its score lands nowhere and the new row waits for the next pass."""
    rows = [
        AEOCheckBrand(id=row_id, sentiment=sentiment.label, sentiment_score=sentiment.score)
        for row_id, sentiment in scored.items()
    ]
    with transaction.atomic():
        written = AEOCheckBrand.objects.for_team(team_id).bulk_update(rows, ["sentiment", "sentiment_score"])
        bump_data_version_on_commit(team_id)
    return written


async def _classify(texts: list[str]) -> list[Mapping[str, float]]:
    import posthog.temporal.ai_observability.sentiment.model as sentiment_model  # noqa: PLC0415 -- ONNX deps

    scores: list[Mapping[str, float]] = []
    for offset in range(0, len(texts), CLASSIFY_BATCH):
        results = await sentiment_model.classify_in_executor(texts[offset : offset + CLASSIFY_BATCH])
        scores.extend(result.scores for result in results)
    return scores


@activity.defn
@close_db_connections
async def classify_aeo_brand_sentiment(inputs: AEOBrandSentimentInputs) -> dict[str, Any]:
    """Score the run's answers that name the brand and have no sentiment yet, then the backlog, for as
    long as the time budget allows.

    A missing model is a deployment problem, not a data problem, so the activity reports it and
    leaves the rows unscored instead of retrying: the next run picks nothing up either, and the
    rows read as "not scored yet" until the worker image carries the model."""
    batch = await database_sync_to_async(_load_pending, thread_sensitive=False)(inputs)
    pending = batch.answers
    pending_brands = await database_sync_to_async(_load_pending_brands, thread_sensitive=False)(inputs.team_id)
    brands = pending_brands.brands
    if pending_brands.unscorable:
        await database_sync_to_async(_mark_unscorable, thread_sensitive=False)(
            inputs.team_id, pending_brands.unscorable
        )
    if not pending and not brands:
        return {"scored": 0, "answers": 0, "brands_scored": 0}

    # Fails fast when the worker image lacks the ONNX dependencies, before any answer is classified.
    try:
        import posthog.temporal.ai_observability.sentiment.model  # noqa: F401, PLC0415 -- ONNX deps
    except (ImportError, FileNotFoundError) as error:
        return _model_unavailable(inputs, pending, error)

    # A pass that runs out of time keeps what it saved; the rest waits for the next pass instead of a
    # retry that would classify it all again.
    deadline = time.monotonic() + SCORING_BUDGET.total_seconds()
    written = classified = 0
    for start in range(0, len(pending), ANSWERS_PER_WRITE):
        if start and time.monotonic() > deadline:
            break
        group = pending[start : start + ANSWERS_PER_WRITE]
        try:
            all_scores = await _classify([sentence.text for answer in group for sentence in answer.sentences])
        except (ImportError, FileNotFoundError) as error:
            return _model_unavailable(inputs, pending, error)
        scored: list[_ScoredAnswer] = []
        position = 0
        for answer in group:
            sentence_scores = all_scores[position : position + len(answer.sentences)]
            position += len(answer.sentences)
            sentiment = aggregate_sentiment(sentence_scores)
            if sentiment is not None:
                scored.append(
                    _ScoredAnswer(
                        check_id=answer.check_id,
                        sentiment=sentiment,
                        sentences=[
                            sentence_sentiment(sentence, scores)
                            for sentence, scores in zip(answer.sentences, sentence_scores)
                        ],
                    )
                )
        written += await database_sync_to_async(_write_scores, thread_sensitive=False)(
            inputs.team_id, batch.own_domains_key, scored
        )
        classified += len(group)
        activity.heartbeat(classified)

    # Other brands go second, so the own brand's sentiment never waits behind them.
    brands_written = brands_classified = 0
    for start in range(0, len(brands), BRANDS_PER_WRITE):
        if (start or classified) and time.monotonic() > deadline:
            break
        group_brands = brands[start : start + BRANDS_PER_WRITE]
        try:
            all_scores = await _classify([sentence.text for brand in group_brands for sentence in brand.sentences])
        except (ImportError, FileNotFoundError) as error:
            return _model_unavailable(inputs, pending, error)
        brand_scores: dict[str, AnswerSentiment] = {}
        position = 0
        for brand in group_brands:
            sentiment = aggregate_sentiment(all_scores[position : position + len(brand.sentences)])
            position += len(brand.sentences)
            if sentiment is not None:
                brand_scores[brand.check_brand_id] = sentiment
        brands_written += await database_sync_to_async(_write_brand_scores, thread_sensitive=False)(
            inputs.team_id, brand_scores
        )
        brands_classified += len(group_brands)
        activity.heartbeat(classified + brands_classified)

    logger.info(
        "aeo_brand_sentiment_scored",
        team_id=inputs.team_id,
        run_id=inputs.run_id,
        scored=written,
        answers=classified,
        remaining=len(pending) - classified,
        brands_scored=brands_written,
        brands_remaining=len(brands) - brands_classified,
    )
    return {"scored": written, "answers": classified, "brands_scored": brands_written}


def _model_unavailable(
    inputs: AEOBrandSentimentInputs, pending: Sequence[_PendingAnswer], error: Exception
) -> dict[str, Any]:
    logger.warning(
        "aeo_brand_sentiment_model_unavailable", team_id=inputs.team_id, run_id=inputs.run_id, error=str(error)
    )
    return {"scored": 0, "answers": len(pending), "error": "model_unavailable"}


@workflow.defn(name=WORKFLOW_NAME)
class AEOBrandSentimentWorkflow(PostHogWorkflow):
    inputs_cls = AEOBrandSentimentInputs

    @workflow.run
    async def run(self, inputs: AEOBrandSentimentInputs) -> dict[str, Any]:
        return await workflow.execute_activity(
            classify_aeo_brand_sentiment,
            inputs,
            start_to_close_timeout=CLASSIFY_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=dt.timedelta(seconds=30)),
        )


def _start(
    team_id: int,
    run_id: str | None,
    workflow_id: str,
    *,
    id_reuse_policy: WorkflowIDReusePolicy,
    id_conflict_policy: WorkflowIDConflictPolicy = WorkflowIDConflictPolicy.UNSPECIFIED,
) -> str:
    client = sync_connect()
    asyncio.run(
        client.start_workflow(
            WORKFLOW_NAME,
            AEOBrandSentimentInputs(team_id=team_id, run_id=run_id),
            id=workflow_id,
            task_queue=settings.AEO_TASK_QUEUE,
            id_reuse_policy=id_reuse_policy,
            id_conflict_policy=id_conflict_policy,
        )
    )
    return workflow_id


def start_backlog_sentiment_scoring(team_id: int) -> str:
    """Scores the team's unscored backlog. A request while a pass is still scoring gets that workflow
    back, so repeated requests never classify the same answers in parallel."""
    return _start(
        team_id,
        None,
        f"{WORKFLOW_NAME}-{team_id}-backlog",
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
    )


def start_brand_sentiment_workflow(team_id: int, run_id: str) -> None:
    """Fire-and-forget: the citation run is already recorded, so a Temporal outage only means
    this run's answers stay unscored."""
    try:
        _start(
            team_id,
            run_id,
            f"{WORKFLOW_NAME}-{team_id}-{run_id}",
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
        )
    except WorkflowAlreadyStartedError:
        logger.info("aeo_brand_sentiment_already_started", team_id=team_id, run_id=run_id)
    except Exception as error:
        logger.exception("aeo_brand_sentiment_start_failed", team_id=team_id, run_id=run_id, error=str(error)[:300])
        capture_exception(error)
    else:
        logger.info("aeo_brand_sentiment_started", team_id=team_id, run_id=run_id)


WORKFLOWS = [AEOBrandSentimentWorkflow]
ACTIVITIES: list[ActivityDefinition] = [classify_aeo_brand_sentiment]
