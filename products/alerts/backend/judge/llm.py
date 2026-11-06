"""A series judge that asks a model instead of fitting a statistical test.

The point is a "just watch this for anything odd" option that needs no statistical
model and no threshold, and that can honor instructions the statistical detectors
cannot express ("only care about drops", "ignore the weekend dip").

One model call decides each check. The model sees the recent series as a table, a chart
of the same points, a plain-English description of what the insight measures, and the
alert author's own notes on what counts as strange. On a sampled share of scheduled checks
from allowlisted teams, a second model is asked the same question as a shadow, so models
can be compared on identical inputs. Its verdict is recorded on the check and never acted on.
"""

import json
import time
import uuid
import hashlib
import threading
from typing import TYPE_CHECKING, Any, Literal

from django.core.cache import cache

import numpy as np
import anthropic
import structlog

from posthog.tasks.alerts.detector import LLM_DETECTOR_MIN_POINTS, llm_detector_lookback

from products.alerts.backend.judge.contract import (
    MAX_CONCURRENT_MODEL_CALLS,
    MAX_PROMPT_POINTS,
    JudgeAttribution,
    LLMDetectorPausedError,
    LLMDetectorUnavailableError,
    SeriesContext,
    SeriesJudgment,
    ShadowJudgment,
)
from products.alerts.backend.judge.models import DEFAULT_JUDGE_MODEL, JUDGE_MODELS, JudgeModel, ModelCall
from products.alerts.backend.judge.prompt import PROMPT_REVISION, SYSTEM_PROMPT, build_prompt, earlier_flag_column
from products.alerts.backend.judge.verdict import LLMDetectionVerdict
from products.alerts.backend.llm_detector_limits import llm_detector_access_error, llm_detector_shadow_config

if TYPE_CHECKING:
    from posthog.models.team import Team

logger = structlog.get_logger(__name__)


def prompt_window(interval: str | None) -> int:
    """How many trailing points the model is shown for a series at this interval."""
    return min(llm_detector_lookback(interval), MAX_PROMPT_POINTS)


MIN_POINTS_TO_JUDGE = LLM_DETECTOR_MIN_POINTS

LLM_DETECTOR_PAUSED_SUFFIX = (
    "This alert is still on and starts checking again once that changes. To keep it running now, "
    "switch it to a statistical detector."
)

LLM_DETECTOR_OUT_OF_CREDITS_MESSAGE = (
    "This alert can't be checked because your organization has used all its AI credits. Add credits in "
    "billing settings, or switch the alert to a statistical detector. The alert is still on and starts "
    "checking again once credits are available."
)

# Bounded so a stalled model call cannot spend the evaluate activity's whole budget,
# which would kill the check before the Temporal retry gets a real attempt.
REQUEST_TIMEOUT_SECONDS = 60.0

# The shadow runs after the primary verdict, inside the same check, so its whole budget is
# added to the check's duration. It gets no retry and a shorter timeout than the primary.
SHADOW_REQUEST_TIMEOUT_SECONDS = 30.0

# The rationale is appended to the breach text that every destination renders. Discord
# rejects a message over 2,000 characters, and the breach prefix and the other breaches in
# the same message need room too.
MAX_RATIONALE_CHARS = 600

# The evaluate activities run AI checks on a dedicated executor of MAX_CONCURRENT_MODEL_CALLS
# threads (see products/alerts/backend/judge/executor.py), so a check there never waits here;
# the wait covers the API's simulate path, whose request threads are its own pool. The wait
# is short so a full pool fails a request fast instead of holding its thread.
MODEL_CALL_SLOT_WAIT_SECONDS = 5.0
# A shadow never waits for a slot, because waiting would delay the check and could take a slot
# that a primary call needs.
SHADOW_SLOT_WAIT_SECONDS = 0.0
_model_call_slots = threading.BoundedSemaphore(MAX_CONCURRENT_MODEL_CALLS)

# The activity that pays for a verdict also writes the AlertCheck, and it retries as a whole,
# so one scheduled check would otherwise buy a verdict once per attempt. Sized past the evaluate
# activity's 12-minute close so it covers every attempt of one check and outlives none of them.
VERDICT_MEMO_TTL_SECONDS = 20 * 60

JudgeRole = Literal["primary", "shadow"]


class _NoFreeModelCallSlotError(LLMDetectorUnavailableError):
    pass


def _verdict_memo_key(
    series: SeriesContext, attribution: JudgeAttribution, *, data: np.ndarray, window: int, model: str
) -> str | None:
    """The memo key for one check's verdict from one model, or None when there is nothing to memoize.

    The key covers the series and its earlier flags as well as the check, so a retry that
    re-queries and gets different numbers or history asks the model again. It covers the model,
    so a shadow never reuses the primary's verdict. A simulation carries no check and is never memoized.
    """
    if not attribution.evaluation_id:
        return None
    fingerprint = hashlib.sha256(np.ascontiguousarray(data, dtype=np.float64).tobytes())
    fingerprint.update(
        json.dumps(
            [
                attribution.evaluation_id,
                series.insight_name,
                series.series_label,
                series.interval,
                series.dates,
                series.metric_description,
                series.instructions,
                window,
                earlier_flag_column(series, length=len(data), window=window),
                model,
                PROMPT_REVISION,
                SYSTEM_PROMPT,
            ],
            separators=(",", ":"),
        ).encode()
    )
    return f"alerts:llm_detector:verdict:{fingerprint.hexdigest()}"


def _is_over_ai_credit_budget(team: "Team") -> bool:
    from ee.billing.quota_limiting import (  # noqa: PLC0415 — keeps the billing query stack off the facade import path
        is_team_over_ai_credit_budget,
    )

    try:
        return is_team_over_ai_credit_budget(team.api_token)
    except Exception:
        # A Redis outage must not error every AI alert of a team that has credits, so this fails open.
        logger.warning("alerts.llm_detector.ai_credit_check_failed", team_id=team.pk, exc_info=True)
        return False


def _is_gateway_credit_refusal(error: Exception) -> bool:
    # The gateway marks its own credit refusals with X-PostHog-Denial. A 402 without that header is the
    # provider blocking the gateway's workspace, which more credits for the organization cannot fix.
    return (
        isinstance(error, anthropic.APIStatusError)
        and error.status_code == 402
        and bool(error.response.headers.get("X-PostHog-Denial"))
    )


def _memoized_verdict(memo_key: str | None) -> LLMDetectionVerdict | None:
    if not memo_key:
        return None
    try:
        stored = cache.get(memo_key)
    except Exception:
        # A cache that cannot be read costs a repeated call, never the check.
        logger.warning("alerts.llm_detector.memo_read_failed", exc_info=True)
        return None
    if not isinstance(stored, str):
        return None
    try:
        return LLMDetectionVerdict.model_validate_json(stored)
    except ValueError:
        return None


def _memoize_verdict(memo_key: str | None, verdict: LLMDetectionVerdict) -> None:
    if not memo_key:
        return
    try:
        cache.set(memo_key, verdict.model_dump_json(), timeout=VERDICT_MEMO_TTL_SECONDS)
    except Exception:
        logger.warning("alerts.llm_detector.memo_write_failed", exc_info=True)


def _in_shadow_sample(evaluation_id: str, rate: float) -> bool:
    # Hashed rather than random, so every retry of one check makes the same decision.
    digest = hashlib.sha256(f"shadow:{evaluation_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64 < rate


def _shadow_model(attribution: JudgeAttribution, primary: JudgeModel) -> JudgeModel | None:
    """The model to shadow this check with, or None when the check is not shadowed."""
    # A simulation has no evaluation id. It is a person waiting on a preview, so it is never shadowed.
    if not attribution.evaluation_id:
        return None
    config = llm_detector_shadow_config(organization_id=attribution.team.organization.id)
    if config is None or attribution.team.id not in config.team_ids:
        return None
    model = JUDGE_MODELS.get(config.model)
    if model is None:
        logger.warning("alerts.llm_detector.unknown_shadow_model", shadow_model=config.model)
        return None
    if model.name == primary.name or not _in_shadow_sample(attribution.evaluation_id, config.rate):
        return None
    return model


class LLMSeriesJudge:
    """Config:
    instructions: str - the author's description of what counts as unusual (optional)
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    def judge_latest(
        self, data: np.ndarray, *, series: SeriesContext, attribution: JudgeAttribution
    ) -> SeriesJudgment | None:
        if len(data) < MIN_POINTS_TO_JUDGE:
            return None

        # An alert created while the organization was in the rollout and had consent on keeps
        # being checked after either is withdrawn. Refusing here covers every path to the
        # model, scheduled or previewed, so the flag is a real stop on spend.
        access_error = llm_detector_access_error(
            distinct_id=str(attribution.user.distinct_id), organization=attribution.team.organization
        )
        if access_error:
            raise LLMDetectorPausedError(f"{access_error} {LLM_DETECTOR_PAUSED_SUFFIX}")
        # A call that is not billable charges no credits, so only a billable call needs them.
        if attribution.is_agent_billable and _is_over_ai_credit_budget(attribution.team):
            raise LLMDetectorPausedError(LLM_DETECTOR_OUT_OF_CREDITS_MESSAGE)

        window = prompt_window(series.interval)
        # Shared by the primary and the shadow call, so LLM analytics shows them as one trace.
        trace_id = f"alert-llm-detector-{uuid.uuid4()}"
        primary = JUDGE_MODELS[DEFAULT_JUDGE_MODEL]
        verdict = self._ask_model(
            model=primary,
            role="primary",
            data=data,
            series=series,
            attribution=attribution,
            window=window,
            trace_id=trace_id,
        )
        return SeriesJudgment(
            fires=verdict.is_anomaly,
            kind=verdict.kind,
            rationale=verdict.rationale[:MAX_RATIONALE_CHARS],
            model=primary.name,
            shadow=self._shadow(
                primary=primary, data=data, series=series, attribution=attribution, window=window, trace_id=trace_id
            ),
        )

    def _shadow(
        self,
        *,
        primary: JudgeModel,
        data: np.ndarray,
        series: SeriesContext,
        attribution: JudgeAttribution,
        window: int,
        trace_id: str,
    ) -> ShadowJudgment | None:
        """Ask the shadow model, if this check is shadowed. Never raises, so it cannot change the check."""
        try:
            model = _shadow_model(attribution, primary)
        except Exception:
            logger.warning("alerts.llm_detector.shadow_config_failed", exc_info=True)
            return None
        if model is None:
            return None

        started_at = time.monotonic()
        try:
            verdict = self._ask_model(
                model=model,
                role="shadow",
                data=data,
                series=series,
                attribution=attribution,
                window=window,
                trace_id=trace_id,
            )
        except _NoFreeModelCallSlotError:
            return ShadowJudgment(model=model.name, latency_ms=_elapsed_ms(started_at), error="no_free_model_call_slot")
        except Exception:
            logger.warning("alerts.llm_detector.shadow_failed", shadow_model=model.name, exc_info=True)
            return ShadowJudgment(model=model.name, latency_ms=_elapsed_ms(started_at), error="model_call_failed")
        return ShadowJudgment(
            model=model.name,
            latency_ms=_elapsed_ms(started_at),
            is_anomaly=verdict.is_anomaly,
            kind=verdict.kind,
            rationale=verdict.rationale[:MAX_RATIONALE_CHARS],
        )

    def _ask_model(
        self,
        *,
        model: JudgeModel,
        role: JudgeRole,
        data: np.ndarray,
        series: SeriesContext,
        attribution: JudgeAttribution,
        window: int,
        trace_id: str,
    ) -> LLMDetectionVerdict:
        memo_key = _verdict_memo_key(series, attribution, data=data, window=window, model=model.name)
        memoized = _memoized_verdict(memo_key)
        if memoized is not None:
            logger.info("alerts.llm_detector.verdict_reused", is_anomaly=memoized.is_anomaly, role=role)
            return memoized

        from ee.hogai.utils.exceptions import LLM_API_EXCEPTIONS  # noqa: PLC0415
        from ee.hogai.utils.feature_flags import is_privacy_mode_enabled  # noqa: PLC0415

        is_shadow = role == "shadow"
        extra_headers: dict[str, str] = {}
        # The shadow exists for our own comparison, so the customer is never charged for it.
        if is_shadow or not attribution.is_agent_billable:
            extra_headers["X-PostHog-Billable"] = "false"
        if is_privacy_mode_enabled(attribution.team):
            extra_headers["X-PostHog-Privacy-Mode"] = "true"
        properties: dict[str, str] = {"llm_detector_role": role}
        if attribution.alert_id:
            properties["alert_id"] = attribution.alert_id
        if attribution.evaluation_id:
            properties["alert_evaluation_id"] = attribution.evaluation_id
        call = ModelCall(
            prompt=build_prompt(data=data, context=series, window=window),
            team_id=attribution.team.id,
            trace_id=trace_id,
            properties=properties,
            extra_headers=extra_headers,
            timeout_seconds=SHADOW_REQUEST_TIMEOUT_SECONDS if is_shadow else REQUEST_TIMEOUT_SECONDS,
            # One in-request retry absorbs a transient blip inside the check's own budget;
            # the Temporal evaluate retry is the outer net. A shadow is not worth a retry.
            max_retries=0 if is_shadow else 1,
        )

        if not _model_call_slots.acquire(
            timeout=SHADOW_SLOT_WAIT_SECONDS if is_shadow else MODEL_CALL_SLOT_WAIT_SECONDS
        ):
            raise _NoFreeModelCallSlotError(
                f"The AI detector is already running {MAX_CONCURRENT_MODEL_CALLS} model calls on this worker."
            )
        try:
            verdict = model.ask(model, call)
        except LLM_API_EXCEPTIONS as error:
            # The in-app budget check above fails open and can read a stale budget, so the gateway's
            # refusal is the backstop and pauses the check the same way.
            if _is_gateway_credit_refusal(error):
                raise LLMDetectorPausedError(LLM_DETECTOR_OUT_OF_CREDITS_MESSAGE) from error
            # Provider credentials, permissions, and model availability are shared across
            # alerts. Disabling an individual alert cannot fix a provider failure.
            raise LLMDetectorUnavailableError(f"The AI detector could not reach the model: {error}") from error
        except Exception as error:
            # Covers an unconfigured gateway, which the client builders report as a ValueError,
            # and a reply that does not parse into a verdict.
            raise LLMDetectorUnavailableError(
                f"The AI detector could not get a verdict from the model: {error}"
            ) from error
        finally:
            _model_call_slots.release()

        if not isinstance(verdict, LLMDetectionVerdict):
            raise LLMDetectorUnavailableError(
                f"The AI detector returned a verdict it could not read (got {type(verdict).__name__})."
            )

        logger.info(
            "alerts.llm_detector.verdict",
            role=role,
            model=model.name,
            is_anomaly=verdict.is_anomaly,
            kind=verdict.kind,
            instructions_present=bool(series.instructions),
            earlier_flags=len(series.earlier_flags),
            points_shown=min(window, len(data)),
        )
        _memoize_verdict(memo_key, verdict)
        return verdict


def _elapsed_ms(started_at: float) -> int:
    return int((time.monotonic() - started_at) * 1000)
