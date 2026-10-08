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
from typing import Any

from django.core.cache import cache

import numpy as np
import structlog
import posthoganalytics

from posthog.tasks.alerts.detector import LLM_DETECTOR_DEFAULT_WINDOW, LLM_DETECTOR_MIN_POINTS

from products.alerts.backend.judge.contract import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    MAX_CONCURRENT_MODEL_CALLS,
    MAX_PROMPT_POINTS,
    JudgeAttribution,
    LLMDetectorMisconfiguredError,
    LLMDetectorUnavailableError,
    SeriesContext,
    SeriesJudgment,
)
from products.alerts.backend.judge.prompt import PROMPT_REVISION, SYSTEM_PROMPT, build_human_message
from products.alerts.backend.judge.verdict import LLMDetectionVerdict
from products.alerts.backend.llm_detector_limits import llm_detector_access_error

logger = structlog.get_logger(__name__)

DEFAULT_WINDOW = LLM_DETECTOR_DEFAULT_WINDOW


def prompt_window(config: dict[str, Any]) -> int:
    """How many trailing points the model is shown for this configuration."""
    return min(int(config.get("window") or DEFAULT_WINDOW), MAX_PROMPT_POINTS)


MIN_POINTS_TO_JUDGE = LLM_DETECTOR_MIN_POINTS

# One constant, matching the anomaly investigation agent. Not exposed per alert: a
# per-alert model field is a cost lever we don't want in the alert editor yet.
LLM_DETECTOR_MODEL = "claude-sonnet-5"

# Own product key in LLM analytics, so this judge's spend is separable from the
# investigation agent's.
LLM_DETECTOR_AI_PRODUCT = "alert_llm_detector"

# The verdict schema is a handful of fields; this only needs to cover that.
MAX_OUTPUT_TOKENS = 1024

# Bounded so a stalled model call cannot spend the evaluate activity's whole budget,
# which would kill the check before the Temporal retry gets a real attempt.
REQUEST_TIMEOUT_SECONDS = 60.0

# The rationale is appended to the breach text that every destination renders. Discord
# rejects a message over 2,000 characters, and the breach prefix and the other breaches in
# the same message need room too.
MAX_RATIONALE_CHARS = 600

# The evaluate activity runs AI checks on a dedicated executor of MAX_CONCURRENT_MODEL_CALLS
# threads (see posthog/temporal/alerts/activities.py), so a check there never waits here;
# the wait covers the API's simulate path, whose request threads are its own pool. The wait
# is short so a full pool fails a request fast instead of holding its thread.
MODEL_CALL_SLOT_WAIT_SECONDS = 5.0
_model_call_slots = threading.BoundedSemaphore(MAX_CONCURRENT_MODEL_CALLS)

# The activity that pays for a verdict also writes the AlertCheck, and it retries as a whole,
# so one scheduled check would otherwise buy a verdict once per attempt. Sized past the evaluate
# activity's 12-minute close so it covers every attempt of one check and outlives none of them.
VERDICT_MEMO_TTL_SECONDS = 20 * 60


def _verdict_memo_key(
    series: SeriesContext, attribution: JudgeAttribution, *, data: np.ndarray, window: int, judge_every_point: bool
) -> str | None:
    """The memo key for one check's verdict, or None when there is nothing to memoize.

    The key covers the series as well as the check, so a retry that re-queries and gets different
    numbers asks the model again. A simulation carries no check and is never memoized.
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
                judge_every_point,
                LLM_DETECTOR_MODEL,
                PROMPT_REVISION,
                SYSTEM_PROMPT,
            ],
            separators=(",", ":"),
        ).encode()
    )
    return f"alerts:llm_detector:verdict:{fingerprint.hexdigest()}"


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
    threshold: float - minimum reported confidence before the alert fires (default: 0.7)
    window: int - how many recent points the model is shown (default: 90)
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    def judge_latest(
        self, data: np.ndarray, *, series: SeriesContext, attribution: JudgeAttribution
    ) -> SeriesJudgment | None:
        return self._judge(data, series=series, attribution=attribution, judge_every_point=False)

    def judge_every_point(
        self, data: np.ndarray, *, series: SeriesContext, attribution: JudgeAttribution
    ) -> SeriesJudgment | None:
        return self._judge(data, series=series, attribution=attribution, judge_every_point=True)

    def _judge(
        self, data: np.ndarray, *, series: SeriesContext, attribution: JudgeAttribution, judge_every_point: bool
    ) -> SeriesJudgment | None:
        if len(data) < MIN_POINTS_TO_JUDGE:
            return None

        window = prompt_window(self.config)
        verdict = self._ask_model(
            data=data, series=series, attribution=attribution, window=window, judge_every_point=judge_every_point
        )
        return self._judgment(verdict, data=data, window=window, judge_every_point=judge_every_point)

    def _ask_model(
        self,
        *,
        data: np.ndarray,
        series: SeriesContext,
        attribution: JudgeAttribution,
        window: int,
        judge_every_point: bool,
    ) -> LLMDetectionVerdict:
        # An alert created while the organization was in the rollout and had consent on keeps
        # being checked after either is withdrawn. Refusing here covers every path to the
        # model, scheduled or previewed, so the flag is a real stop on spend.
        access_error = llm_detector_access_error(
            distinct_id=str(attribution.user.distinct_id), organization=attribution.team.organization
        )
        if access_error:
            raise LLMDetectorMisconfiguredError(
                f"{access_error} This alert cannot be checked until that changes. Switch it to a statistical "
                "detector to keep it running."
            )

        memo_key = _verdict_memo_key(series, attribution, data=data, window=window, judge_every_point=judge_every_point)
        memoized = _memoized_verdict(memo_key)
        if memoized is not None:
            logger.info("alerts.llm_detector.verdict_reused", is_anomaly=memoized.is_anomaly)
            return memoized

        # Deferred so importing the evaluation package does not pull langchain into every
        # process that touches an alert.
        from langchain_core.callbacks import BaseCallbackHandler  # noqa: PLC0415
        from langchain_core.messages import HumanMessage, SystemMessage  # noqa: PLC0415
        from langchain_core.runnables import RunnableConfig  # noqa: PLC0415
        from posthoganalytics.ai.langchain.callbacks import CallbackHandler  # noqa: PLC0415

        from ee.hogai.llm import MaxChatAnthropic  # noqa: PLC0415
        from ee.hogai.utils.exceptions import LLM_API_EXCEPTIONS  # noqa: PLC0415
        from ee.hogai.utils.feature_flags import is_privacy_mode_enabled  # noqa: PLC0415

        instructions_present = bool(series.instructions)
        # No temperature: Sonnet 5 rejects non-default sampling params with a 400.
        model = MaxChatAnthropic(
            model=LLM_DETECTOR_MODEL,
            team=attribution.team,
            user=attribution.user,
            billable=True,
            # The series, its definition, and the author's notes are the whole context; the
            # project/org preamble would only dilute a single-judgment prompt.
            inject_context=False,
            streaming=False,
            disable_streaming=True,
            stream_usage=False,
            # One in-request retry absorbs a transient blip inside the check's own budget;
            # the Temporal evaluate retry is the outer net.
            max_retries=1,
            max_tokens=MAX_OUTPUT_TOKENS,
            thinking={"type": "disabled"},
            default_request_timeout=REQUEST_TIMEOUT_SECONDS,
            posthog_properties={"ai_product": LLM_DETECTOR_AI_PRODUCT},
        ).with_structured_output(LLMDetectionVerdict, include_raw=False)

        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(
                content=build_human_message(
                    data=data, context=series, window=window, judge_every_point=judge_every_point
                )
            ),
        ]

        callbacks: list[BaseCallbackHandler] = []
        if posthoganalytics.default_client is not None:
            callbacks.append(
                CallbackHandler(
                    posthoganalytics.default_client,
                    distinct_id=str(attribution.team.id),
                    trace_id=f"alert-llm-detector-{uuid.uuid4()}",
                    properties={"ai_product": LLM_DETECTOR_AI_PRODUCT, "team_id": attribution.team.id},
                    privacy_mode=is_privacy_mode_enabled(attribution.team),
                )
            )

        if not _model_call_slots.acquire(timeout=MODEL_CALL_SLOT_WAIT_SECONDS):
            raise LLMDetectorUnavailableError(
                f"The AI detector is already running {MAX_CONCURRENT_MODEL_CALLS} model calls on this worker."
            )
        try:
            verdict = model.invoke(
                messages,
                config=RunnableConfig(
                    callbacks=callbacks, configurable={"is_agent_billable": attribution.is_agent_billable}
                ),
            )
        except LLM_API_EXCEPTIONS as error:
            # Provider credentials, permissions, and model availability are shared across
            # alerts. Disabling an individual alert cannot fix a provider failure.
            raise LLMDetectorUnavailableError(f"The AI detector could not reach the model: {error}") from error
        except Exception as error:
            raise LLMDetectorUnavailableError(f"The AI detector could not read the model response: {error}") from error
        finally:
            _model_call_slots.release()

        if not isinstance(verdict, LLMDetectionVerdict):
            raise LLMDetectorUnavailableError(
                f"The AI detector returned a verdict it could not read (got {type(verdict).__name__})."
            )

        logger.info(
            "alerts.llm_detector.verdict",
            is_anomaly=verdict.is_anomaly,
            confidence=verdict.confidence,
            kind=verdict.kind,
            judge_every_point=judge_every_point,
            instructions_present=instructions_present,
            points_shown=min(window, len(data)),
        )
        _memoize_verdict(memo_key, verdict)
        return verdict

    def _judgment(
        self, verdict: LLMDetectionVerdict, *, data: np.ndarray, window: int, judge_every_point: bool
    ) -> SeriesJudgment:
        configured_threshold = self.config.get("threshold")
        threshold = float(configured_threshold if configured_threshold is not None else DEFAULT_CONFIDENCE_THRESHOLD)
        confident = verdict.confidence >= threshold
        fires = verdict.is_anomaly and confident

        index_offset = max(0, len(data) - window)
        reported_indices = [index + index_offset for index in verdict.triggered_indices]
        score_indices = self._clamp_indices(reported_indices, length=len(data)) if verdict.is_anomaly else []
        indices = score_indices
        latest_point_flagged = (len(data) - 1) in indices
        if not judge_every_point:
            # A live check judges one point. The prompt asks the model to list the final index
            # when, and only when, that point is the anomaly, so a verdict that flags only
            # history (or nothing) must not page anyone about a normal current value.
            fires = fires and latest_point_flagged
            indices = [len(data) - 1] if fires else []
        elif not fires:
            indices = []

        anomaly_score = self._anomaly_score(verdict)
        return SeriesJudgment(
            fires=fires,
            verdict_is_anomaly=verdict.is_anomaly,
            confidence=verdict.confidence,
            kind=verdict.kind,
            rationale=verdict.rationale[:MAX_RATIONALE_CHARS],
            model=LLM_DETECTOR_MODEL,
            score=anomaly_score,
            triggered_indices=tuple(indices),
            all_scores=self._scores(anomaly_score, indices=score_indices, length=len(data))
            if judge_every_point
            else (anomaly_score,),
            below_threshold=verdict.is_anomaly and not confident,
            latest_point_not_flagged=verdict.is_anomaly and not judge_every_point and not latest_point_flagged,
        )

    @staticmethod
    def _anomaly_score(verdict: LLMDetectionVerdict) -> float:
        """The verdict on the scale the threshold gate and the check history chart read scores on.

        The model reports confidence in its verdict, whichever way it went. A confident "no
        anomaly" is a low anomaly score; stored raw, it would plot above the threshold as a
        check that would have fired.
        """
        return verdict.confidence if verdict.is_anomaly else 1.0 - verdict.confidence

    @staticmethod
    def _clamp_indices(indices: list[int], *, length: int) -> list[int]:
        """Drop indices the model invented outside the series, and de-duplicate."""
        return sorted({index for index in indices if 0 <= index < length})

    @staticmethod
    def _scores(confidence: float, *, indices: list[int], length: int) -> tuple[float | None, ...]:
        """One score per point for the simulation chart.

        The model reports a single confidence for the whole judgment rather than a score
        per point, so only the points it flagged carry one. The rest are left unscored
        instead of being given a made-up number.
        """
        flagged = set(indices)
        return tuple(confidence if index in flagged else None for index in range(length))
