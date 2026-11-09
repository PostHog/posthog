"""Scores brand sentiment for one citation run.

The ONNX sentiment model and its dependencies are only in the image that serves
the evals Temporal queue, so the runner cannot classify inline: it starts this
workflow, and the activity reads the run's answers back from Postgres, scores the
sentences that name the brand, and writes the label and score to the check rows.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import dataclasses
from collections.abc import Sequence
from typing import Any

from django.conf import settings
from django.utils import timezone

import structlog
from temporalio import activity, workflow
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.client import sync_connect
from posthog.temporal.common.utils import close_db_connections

from products.aeo.backend.brand import brand_regex
from products.aeo.backend.models import AEOCitationCheck
from products.aeo.backend.sentiment import aggregate_sentiment, brand_sentences

logger = structlog.get_logger(__name__)

WORKFLOW_NAME = "aeo-brand-sentiment"
# One run is at most ~150 answers x 20 sentences on a CPU model, well inside this.
CLASSIFY_TIMEOUT = dt.timedelta(minutes=15)
CLASSIFY_BATCH = 32
# Answers scored before the setting was turned on, or missed by a failed run, are picked up from
# this far back, which matches the window the prompt report shows.
BACKLOG_WINDOW = dt.timedelta(days=30)
MAX_ROWS_PER_RUN = 2000


@dataclasses.dataclass(frozen=True)
class AEOBrandSentimentInputs:
    team_id: int
    run_id: str


@dataclasses.dataclass(frozen=True)
class _PendingAnswer:
    check_id: str
    sentences: list[str]


def _load_pending(inputs: AEOBrandSentimentInputs) -> list[_PendingAnswer]:
    """The run's unscored answers, then the team's other unscored answers from the backlog window,
    oldest first, capped so one activity never scans an unbounded history.

    Only answers that name the brand count toward the cap: an answer without a mention stays NULL
    forever, so letting it fill the slice would starve newer answers that can be scored.

    Two concurrent runs can both pick up the same backlog row. The writes are idempotent (the same
    text scores the same), so that only costs a duplicate classification, and no transaction is
    held across the model call that a row lock could ride on."""
    target_domains: list[str] = settings.AEO_TARGET_DOMAINS
    regex = brand_regex(target_domains)
    if regex is None:
        return []
    unscored = AEOCitationCheck.objects.for_team(inputs.team_id).filter(
        check_failed=False, brand_sentiment__isnull=True, answer_text__iregex=regex
    )
    own_rows = list(unscored.filter(run_id=inputs.run_id).order_by("created_at").values_list("id", "answer_text"))
    backlog_rows = list(
        unscored.exclude(run_id=inputs.run_id)
        .filter(created_at__gte=timezone.now() - BACKLOG_WINDOW)
        .order_by("created_at")
        .values_list("id", "answer_text")[: max(0, MAX_ROWS_PER_RUN - len(own_rows))]
    )
    pending = [
        _PendingAnswer(check_id=str(check_id), sentences=brand_sentences(text, target_domains))
        for check_id, text in [*own_rows, *backlog_rows]
    ]
    return [answer for answer in pending if answer.sentences]


def _write_scores(team_id: int, scored: Sequence[tuple[str, str, float]]) -> None:
    rows = [
        AEOCitationCheck(id=check_id, brand_sentiment=label, brand_sentiment_score=score)
        for check_id, label, score in scored
    ]
    AEOCitationCheck.objects.for_team(team_id).bulk_update(rows, ["brand_sentiment", "brand_sentiment_score"])


@activity.defn
@close_db_connections
async def classify_aeo_brand_sentiment(inputs: AEOBrandSentimentInputs) -> dict[str, Any]:
    """Score every answer of the run that names the brand and has no sentiment yet.

    A missing model is a deployment problem, not a data problem, so the activity reports it and
    leaves the rows unscored instead of retrying: the next run picks nothing up either, and the
    rows read as "not scored yet" until the worker image carries the model."""
    pending = await database_sync_to_async(_load_pending, thread_sensitive=False)(inputs)
    if not pending:
        return {"scored": 0, "answers": 0}

    texts = [sentence for answer in pending for sentence in answer.sentences]
    try:
        import posthog.temporal.ai_observability.sentiment.model as sentiment_model  # noqa: PLC0415 -- ONNX deps

        results = []
        for start in range(0, len(texts), CLASSIFY_BATCH):
            results.extend(await asyncio.to_thread(sentiment_model.classify, texts[start : start + CLASSIFY_BATCH]))
    except (ImportError, FileNotFoundError) as error:
        logger.warning(
            "aeo_brand_sentiment_model_unavailable", team_id=inputs.team_id, run_id=inputs.run_id, error=str(error)
        )
        return {"scored": 0, "answers": len(pending), "error": "model_unavailable"}

    scored: list[tuple[str, str, float]] = []
    position = 0
    for answer in pending:
        sentence_scores = [result.scores for result in results[position : position + len(answer.sentences)]]
        position += len(answer.sentences)
        sentiment = aggregate_sentiment(sentence_scores)
        if sentiment is not None:
            scored.append((answer.check_id, sentiment.label, sentiment.score))
    await database_sync_to_async(_write_scores, thread_sensitive=False)(inputs.team_id, scored)
    logger.info("aeo_brand_sentiment_scored", team_id=inputs.team_id, run_id=inputs.run_id, scored=len(scored))
    return {"scored": len(scored), "answers": len(pending)}


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


def start_brand_sentiment_workflow(team_id: int, run_id: str) -> None:
    """Fire-and-forget: the citation run is already recorded, so a Temporal outage only means
    this run's answers stay unscored."""
    inputs = AEOBrandSentimentInputs(team_id=team_id, run_id=run_id)
    try:
        client = sync_connect()
        asyncio.run(
            client.start_workflow(
                WORKFLOW_NAME,
                inputs,
                id=f"{WORKFLOW_NAME}-{team_id}-{run_id}",
                task_queue=settings.LLMA_EVALS_TASK_QUEUE,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
            )
        )
    except WorkflowAlreadyStartedError:
        logger.info("aeo_brand_sentiment_already_started", team_id=team_id, run_id=run_id)
    except Exception as error:
        logger.exception("aeo_brand_sentiment_start_failed", team_id=team_id, run_id=run_id, error=str(error)[:300])
        capture_exception(error)
    else:
        logger.info("aeo_brand_sentiment_started", team_id=team_id, run_id=run_id)


WORKFLOWS = [AEOBrandSentimentWorkflow]
ACTIVITIES = [classify_aeo_brand_sentiment]
