"""Runs an unsaved LLM judge on a few real units, so its author sees results before creating it."""

import time
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager, nullcontext
from typing import Any

from django.core.cache import cache
from django.core.exceptions import ValidationError

import structlog
from temporalio.exceptions import ApplicationError

from posthog.hogql_queries.ai.ai_table_resolver import AIEventsUnavailableError
from posthog.models import Team, User
from posthog.temporal.ai_observability.evaluation_llm_judge import TransientJudgeError
from posthog.temporal.ai_observability.evaluation_types import EvaluationActivityResult

from ...facade import contracts
from ...llm.errors import LLMError
from ...models.evaluation_configs import EvaluationType
from ...models.model_configuration import LLMModelConfiguration
from ...models.provider_keys import LLMProviderKey
from .preview_outcomes import PreviewGrader, preview_grader
from .preview_queries import UnitPreview
from .preview_units import preview_sampling, preview_units

logger = structlog.get_logger(__name__)

# Each unit is a paid judge call on the customer's key, made while the request waits.
MAX_JUDGE_TEST_UNITS = 3
JUDGE_TEST_BUDGET_SECONDS = 60
# Past the budget plus one call running to the provider's 300-second timeout, so the lock outlives any request
# yet frees itself if the worker dies before it can release it.
JUDGE_TEST_LOCK_SECONDS = 600
_UNSAVED_EVALUATION_ID = "unsaved"


def _model_configuration(team: Team, model: contracts.JudgeModel | None) -> dict[str, Any] | None:
    """The model settings the judge resolves its provider key from. Raises `JudgeModelError` for a pinned key
    that is not this team's or belongs to another provider, which would send the key to the wrong provider."""
    if model is None:
        return None
    provider_key = None
    if model.provider_key_id:
        provider_key = LLMProviderKey.objects.filter(id=model.provider_key_id, team=team).first()
        if provider_key is None:
            raise contracts.JudgeModelError("Provider key not found")
    try:
        LLMModelConfiguration(team=team, provider=model.provider, model=model.model, provider_key=provider_key).clean()
    except ValidationError as error:
        raise contracts.JudgeModelError(" ".join(error.messages)) from error
    return {"provider": model.provider, "model": model.model, "provider_key_id": model.provider_key_id}


def _evaluation_payload(team: Team, judge: contracts.UnsavedJudge) -> dict[str, Any]:
    """The unsaved judge in the shape the live judge functions read a saved evaluation in."""
    return {
        "id": _UNSAVED_EVALUATION_ID,
        "name": "Unsaved evaluation",
        "evaluation_type": EvaluationType.LLM_JUDGE.value,
        "evaluation_config": dict(judge.evaluation_config),
        "output_type": judge.output_type,
        "output_config": dict(judge.output_config),
        "team_id": team.pk,
        # Resolution only ever runs on the team's own provider key, so a keyless config is a per-row error.
        "model_configuration": _model_configuration(team, judge.model),
        "enabled": False,
        "deleted": False,
    }


def _error_message(error: Exception) -> str:
    # These carry messages written for the user, such as a rejected key or an exhausted rate limit.
    if isinstance(error, ApplicationError | LLMError | TransientJudgeError):
        return str(error)
    logger.exception("Evaluation judge test failed", error_class=type(error).__name__)
    return "The evaluation could not run on this sample. Try again."


def _row(
    *,
    unit_id: str,
    target: contracts.EvaluationUnitKind,
    preview: UnitPreview | None,
    grader: PreviewGrader,
    result: EvaluationActivityResult | None = None,
    error: str | None = None,
) -> contracts.EvaluationTestResult:
    verdict: bool | None = None
    reasoning: str | None = None
    score: float | None = None
    categories: list[str] | None = None
    if result is not None:
        if result.get("skipped"):
            error = result["reasoning"]
        else:
            verdict = result.get("verdict")
            reasoning = result["reasoning"] or None
            score = result.get("score") if result["result_type"] == "numeric" else None
            categories = result.get("categories") if result["result_type"] == "categorical" else None
    return contracts.EvaluationTestResult(
        sample_id=unit_id,
        sample_type=target,
        event_uuid=unit_id if target == "generation" else None,
        trace_id=preview.trace_id if preview else None,
        input_preview=preview.io.input if preview else "",
        output_preview=preview.io.output if preview else "",
        result=verdict,
        score=score,
        categories=categories,
        reasoning=reasoning,
        error=error,
        outcome=grader.outcome(error=error, result=verdict, score=score, categories=categories),
    )


def run_judge_test(
    team: Team,
    user: User,
    judge: contracts.UnsavedJudge,
    scope: contracts.EvaluationPreviewScope,
    sample_ids: Sequence[str] | None,
    *,
    reading: Callable[[], AbstractContextManager[None]] = nullcontext,
) -> list[contracts.EvaluationTestResult]:
    """Judge up to `MAX_JUDGE_TEST_UNITS` units: exactly `sample_ids`, or the latest ones the scope matches.
    Saves nothing and emits no results.

    `reading` wraps each ClickHouse read, so a caller can hold its query slots for them without holding them
    through the model calls.

    Raises `JudgeModelError` for a provider key the model cannot use, and `JudgeTestAlreadyRunningError` while
    this user's previous test is still running.
    """
    evaluation = _evaluation_payload(team, judge)
    # One test per user at a time: a single call can run to the provider's timeout, which the budget below
    # cannot cut short, so this bounds how many web workers one user holds to one. Taken before the reads, so
    # a second click costs nothing.
    running_key = f"llma_eval_judge_test_running:{user.pk}"
    if not cache.add(running_key, True, timeout=JUDGE_TEST_LOCK_SECONDS):
        raise contracts.JudgeTestAlreadyRunningError()
    try:
        units = preview_units(scope.target)
        try:
            with reading():
                loaded = units.load(team, user, preview_sampling(team, scope), MAX_JUDGE_TEST_UNITS, sample_ids)
                previews = units.previews(team, user, loaded)
        except AIEventsUnavailableError:
            return []

        grader = preview_grader(judge.output_type, judge.output_config)
        # ponytail: sequential judge calls, up to three; run them concurrently if the wait gets long.
        # A slow model can take minutes per call, so later calls are skipped once the request has run long
        # enough, rather than being billed after the browser has already given up.
        started = time.monotonic()
        rows = []
        for unit in loaded:
            unit_id = units.unit_id(unit)
            result: EvaluationActivityResult | None = None
            error: str | None = None
            if time.monotonic() - started > JUDGE_TEST_BUDGET_SECONDS:
                error = "Not run, because the earlier runs took over a minute."
            else:
                try:
                    result = units.judge(evaluation, unit, user, reading)
                except Exception as judge_error:
                    error = _error_message(judge_error)
            rows.append(
                _row(
                    unit_id=unit_id,
                    target=scope.target,
                    preview=previews.get(unit_id),
                    grader=grader,
                    result=result,
                    error=error,
                )
            )
        return rows
    finally:
        cache.delete(running_key)
