"""A series judge that asks a model instead of fitting a statistical test.

The point is a "just watch this for anything odd" option that needs no statistical
model and no threshold, and that can honor instructions the statistical detectors
cannot express ("only care about drops", "ignore the weekend dip").

One model call per check. The model sees the recent series as a table, a chart of the
same points, a plain-English description of what the insight measures, and the alert
author's own notes on what counts as strange.
"""

import json
import uuid
import hashlib
import threading
from typing import TYPE_CHECKING, Any

from django.core.cache import cache

import numpy as np
import anthropic
import structlog

from posthog.llm.gateway_client import build_ai_gateway_anthropic_client
from posthog.tasks.alerts.detector import LLM_DETECTOR_MIN_POINTS, llm_detector_lookback

from products.alerts.backend.judge.contract import (
    MAX_CONCURRENT_MODEL_CALLS,
    MAX_PROMPT_POINTS,
    JudgeAttribution,
    LLMDetectorPausedError,
    LLMDetectorUnavailableError,
    SeriesContext,
    SeriesJudgment,
)
from products.alerts.backend.judge.prompt import (
    PROMPT_REVISION,
    SYSTEM_PROMPT,
    build_human_message,
    earlier_flag_column,
)
from products.alerts.backend.judge.verdict import LLMDetectionVerdict
from products.alerts.backend.llm_detector_limits import llm_detector_access_error

if TYPE_CHECKING:
    from posthog.models.team import Team

logger = structlog.get_logger(__name__)


def prompt_window(interval: str | None) -> int:
    """How many trailing points the model is shown for a series at this interval."""
    return min(llm_detector_lookback(interval), MAX_PROMPT_POINTS)


MIN_POINTS_TO_JUDGE = LLM_DETECTOR_MIN_POINTS

# One constant. Not exposed per alert: a per-alert model field is a cost lever we
# don't want in the alert editor yet.
LLM_DETECTOR_MODEL = "claude-haiku-5-5"

# Own product key in LLM analytics, so this judge's spend is separable from the
# investigation agent's.
LLM_DETECTOR_AI_PRODUCT = "alert_llm_detector"

LLM_DETECTOR_PAUSED_SUFFIX = (
    "This alert is still on and starts checking again once that changes. To keep it running now, "
    "switch it to a statistical detector."
)

LLM_DETECTOR_OUT_OF_CREDITS_MESSAGE = (
    "This alert can't be checked because your organization has used all its AI credits. Add credits in "
    "billing settings, or switch the alert to a statistical detector. The alert is still on and starts "
    "checking again once credits are available."
)

# The verdict schema is a handful of fields; this only needs to cover that.
MAX_OUTPUT_TOKENS = 1024

# Bounded so a stalled model call cannot spend the evaluate activity's whole budget,
# which would kill the check before the Temporal retry gets a real attempt.
REQUEST_TIMEOUT_SECONDS = 60.0

# The rationale is appended to the breach text that every destination renders. Discord
# rejects a message over 2,000 characters, and the breach prefix and the other breaches in
# the same message need room too.
MAX_RATIONALE_CHARS = 600

# The evaluate activities run AI checks on a dedicated executor of MAX_CONCURRENT_MODEL_CALLS
# threads (see products/alerts/backend/judge/executor.py), so a check there never waits here;
# the wait covers the API's simulate path, whose request threads are its own pool. The wait
# is short so a full pool fails a request fast instead of holding its thread.
MODEL_CALL_SLOT_WAIT_SECONDS = 5.0
_model_call_slots = threading.BoundedSemaphore(MAX_CONCURRENT_MODEL_CALLS)

# The activity that pays for a verdict also writes the AlertCheck, and it retries as a whole,
# so one scheduled check would otherwise buy a verdict once per attempt. Sized past the evaluate
# activity's 12-minute close so it covers every attempt of one check and outlives none of them.
VERDICT_MEMO_TTL_SECONDS = 20 * 60


def _verdict_memo_key(
    series: SeriesContext, attribution: JudgeAttribution, *, data: np.ndarray, window: int
) -> str | None:
    """The memo key for one check's verdict, or None when there is nothing to memoize.

    The key covers the series and its earlier flags as well as the check, so a retry that
    re-queries and gets different numbers or history asks the model again. A simulation carries
    no check and is never memoized.
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
                LLM_DETECTOR_MODEL,
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

        verdict = self._ask_model(
            data=data, series=series, attribution=attribution, window=prompt_window(series.interval)
        )
        return SeriesJudgment(
            fires=verdict.is_anomaly,
            kind=verdict.kind,
            rationale=verdict.rationale[:MAX_RATIONALE_CHARS],
            model=LLM_DETECTOR_MODEL,
        )

    def _ask_model(
        self,
        *,
        data: np.ndarray,
        series: SeriesContext,
        attribution: JudgeAttribution,
        window: int,
    ) -> LLMDetectionVerdict:
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

        memo_key = _verdict_memo_key(series, attribution, data=data, window=window)
        memoized = _memoized_verdict(memo_key)
        if memoized is not None:
            logger.info("alerts.llm_detector.verdict_reused", is_anomaly=memoized.is_anomaly)
            return memoized

        from ee.hogai.utils.exceptions import LLM_API_EXCEPTIONS  # noqa: PLC0415
        from ee.hogai.utils.feature_flags import is_privacy_mode_enabled  # noqa: PLC0415

        instructions_present = bool(series.instructions)
        try:
            client = build_ai_gateway_anthropic_client(
                ai_product=LLM_DETECTOR_AI_PRODUCT,
                trace_id=f"alert-llm-detector-{uuid.uuid4()}",
                team_id=attribution.team.id,
            )
        except ValueError as error:
            raise LLMDetectorUnavailableError(f"The AI detector could not reach the model: {error}") from error

        extra_headers: dict[str, str] = {}
        if not attribution.is_agent_billable:
            extra_headers["X-PostHog-Billable"] = "false"
        if is_privacy_mode_enabled(attribution.team):
            extra_headers["X-PostHog-Privacy-Mode"] = "true"

        with client:
            if not _model_call_slots.acquire(timeout=MODEL_CALL_SLOT_WAIT_SECONDS):
                raise LLMDetectorUnavailableError(
                    f"The AI detector is already running {MAX_CONCURRENT_MODEL_CALLS} model calls on this worker."
                )
            try:
                # One in-request retry absorbs a transient blip inside the check's own budget;
                # the Temporal evaluate retry is the outer net.
                response = client.with_options(max_retries=1, timeout=REQUEST_TIMEOUT_SECONDS).messages.parse(
                    model=LLM_DETECTOR_MODEL,
                    max_tokens=MAX_OUTPUT_TOKENS,
                    # No temperature: Haiku 5.5 rejects non-default sampling params with a 400. Disabled
                    # thinking is accepted only at effort "high" or below, so do not raise the effort past it.
                    thinking={"type": "disabled"},
                    system=SYSTEM_PROMPT,
                    messages=[
                        {
                            "role": "user",
                            "content": build_human_message(data=data, context=series, window=window),  # type: ignore[typeddict-item]
                        }
                    ],
                    output_format=LLMDetectionVerdict,
                    extra_headers=extra_headers,
                )
                verdict = response.parsed_output
            except LLM_API_EXCEPTIONS as error:
                # The in-app budget check above fails open and can read a stale budget, so the gateway's
                # refusal is the backstop and pauses the check the same way.
                if _is_gateway_credit_refusal(error):
                    raise LLMDetectorPausedError(LLM_DETECTOR_OUT_OF_CREDITS_MESSAGE) from error
                # Provider credentials, permissions, and model availability are shared across
                # alerts. Disabling an individual alert cannot fix a provider failure.
                raise LLMDetectorUnavailableError(f"The AI detector could not reach the model: {error}") from error
            except Exception as error:
                raise LLMDetectorUnavailableError(
                    f"The AI detector could not read the model response: {error}"
                ) from error
            finally:
                _model_call_slots.release()

        if not isinstance(verdict, LLMDetectionVerdict):
            raise LLMDetectorUnavailableError(
                f"The AI detector returned a verdict it could not read (got {type(verdict).__name__})."
            )

        logger.info(
            "alerts.llm_detector.verdict",
            is_anomaly=verdict.is_anomaly,
            kind=verdict.kind,
            instructions_present=instructions_present,
            earlier_flags=len(series.earlier_flags),
            points_shown=min(window, len(data)),
        )
        _memoize_verdict(memo_key, verdict)
        return verdict
