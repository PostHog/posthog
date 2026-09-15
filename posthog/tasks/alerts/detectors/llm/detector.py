"""An anomaly detector that asks a model to judge the series.

The point is a "just watch this for anything odd" option that needs no statistical
model and no threshold, and that can honor instructions the statistical detectors
cannot express ("only care about drops", "ignore the weekend dip").

One model call per check. The model sees the recent series as a table, a chart of the
same points, a plain-English description of what the insight measures, and the alert
author's own notes on what counts as strange.
"""

import uuid
from typing import Any

import numpy as np
import structlog
import posthoganalytics

from posthog.schema import DetectorType

from posthog.tasks.alerts.detectors.base import BaseDetector, DetectionContext, DetectionResult
from posthog.tasks.alerts.detectors.llm.errors import LLMDetectorMisconfiguredError, LLMDetectorUnavailableError
from posthog.tasks.alerts.detectors.llm.prompt import SYSTEM_PROMPT, build_human_message
from posthog.tasks.alerts.detectors.llm.verdict import LLMDetectionVerdict
from posthog.tasks.alerts.detectors.registry import register_detector

logger = structlog.get_logger(__name__)

# One constant, matching the anomaly investigation agent. Not exposed per alert: a
# per-alert model field is a cost lever we don't want in the alert editor yet.
LLM_DETECTOR_MODEL = "claude-sonnet-5"

# Own product key in LLM analytics, so this detector's spend is separable from the
# investigation agent's.
LLM_DETECTOR_AI_PRODUCT = "alert_llm_detector"

# The verdict schema is a handful of fields; this only needs to cover that.
MAX_OUTPUT_TOKENS = 1024

# Bounded so a stalled model call cannot spend the evaluate activity's whole budget,
# which would kill the check before the Temporal retry gets a real attempt.
REQUEST_TIMEOUT_SECONDS = 60.0

DEFAULT_CONFIDENCE_THRESHOLD = 0.7
DEFAULT_WINDOW = 90

# Enough history for the model to see a weekly shape at any cadence, while bounding
# what one check can send. Caps the configured window.
MAX_PROMPT_POINTS = 400

MIN_POINTS_TO_JUDGE = 5


@register_detector(DetectorType.LLM)
class LLMDetector(BaseDetector):
    """Config:
    instructions: str - the author's description of what counts as unusual (optional)
    threshold: float - minimum reported confidence before the alert fires (default: 0.7)
    window: int - how many recent points the model is shown (default: 90)
    """

    def detect(self, data: np.ndarray) -> DetectionResult:
        raise LLMDetectorMisconfiguredError(
            "The AI detector needs the series context (dates, metric definition, project) and so is "
            "only reachable through detect_in_context."
        )

    def detect_batch(self, data: np.ndarray) -> DetectionResult:
        raise LLMDetectorMisconfiguredError(
            "The AI detector needs the series context (dates, metric definition, project) and so is "
            "only reachable through detect_batch_in_context."
        )

    def detect_in_context(self, data: np.ndarray, context: DetectionContext) -> DetectionResult:
        return self._judge(data, context, judge_every_point=False)

    def detect_batch_in_context(self, data: np.ndarray, context: DetectionContext) -> DetectionResult:
        return self._judge(data, context, judge_every_point=True)

    def _judge(self, data: np.ndarray, context: DetectionContext, *, judge_every_point: bool) -> DetectionResult:
        if not self._validate_data(data, min_length=MIN_POINTS_TO_JUDGE):
            return DetectionResult(is_anomaly=False)

        window = min(int(self.config.get("window") or DEFAULT_WINDOW), MAX_PROMPT_POINTS)
        verdict = self._ask_model(data=data, context=context, window=window, judge_every_point=judge_every_point)
        return self._to_result(verdict, data=data, window=window, judge_every_point=judge_every_point)

    def _ask_model(
        self,
        *,
        data: np.ndarray,
        context: DetectionContext,
        window: int,
        judge_every_point: bool,
    ) -> LLMDetectionVerdict:
        if context.team is None or context.user is None:
            raise LLMDetectorMisconfiguredError(
                "The AI detector needs a project and a user to attribute its model calls to. This "
                "alert has neither, which happens when the person who created it was deleted. "
                "Recreate the alert to fix it."
            )

        # Deferred so importing the detector registry does not pull langchain into every
        # process that touches an alert.
        from langchain_core.messages import HumanMessage, SystemMessage  # noqa: PLC0415
        from posthoganalytics.ai.langchain.callbacks import CallbackHandler  # noqa: PLC0415

        from ee.hogai.llm import MaxChatAnthropic  # noqa: PLC0415
        from ee.hogai.utils.exceptions import LLM_API_EXCEPTIONS, LLM_TRANSIENT_EXCEPTIONS  # noqa: PLC0415

        instructions_present = bool(context.instructions)
        # No temperature: Sonnet 5 rejects non-default sampling params with a 400.
        model = MaxChatAnthropic(
            model=LLM_DETECTOR_MODEL,
            team=context.team,
            user=context.user,
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
            default_request_timeout=REQUEST_TIMEOUT_SECONDS,
            posthog_properties={"ai_product": LLM_DETECTOR_AI_PRODUCT},
        ).with_structured_output(LLMDetectionVerdict, include_raw=False)

        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(
                content=build_human_message(
                    data=data, context=context, window=window, judge_every_point=judge_every_point
                )
            ),
        ]

        callbacks = []
        if posthoganalytics.default_client is not None:
            callbacks.append(
                CallbackHandler(
                    posthoganalytics.default_client,
                    distinct_id=str(context.team.id),
                    trace_id=f"alert-llm-detector-{uuid.uuid4()}",
                    properties={"ai_product": LLM_DETECTOR_AI_PRODUCT, "team_id": context.team.id},
                )
            )

        try:
            verdict = model.invoke(messages, config={"callbacks": callbacks})
        except LLM_TRANSIENT_EXCEPTIONS as error:
            raise LLMDetectorUnavailableError(f"The AI detector could not reach the model: {error}") from error
        except LLM_API_EXCEPTIONS as error:
            raise LLMDetectorMisconfiguredError(
                f"The AI detector request was rejected by the model: {error}"
            ) from error
        except Exception as error:
            raise LLMDetectorUnavailableError(f"The AI detector could not read the model response: {error}") from error

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
        return verdict

    def _to_result(
        self, verdict: LLMDetectionVerdict, *, data: np.ndarray, window: int, judge_every_point: bool
    ) -> DetectionResult:
        configured_threshold = self.config.get("threshold")
        threshold = float(configured_threshold if configured_threshold is not None else DEFAULT_CONFIDENCE_THRESHOLD)
        confident = verdict.confidence >= threshold
        is_anomaly = verdict.is_anomaly and confident

        index_offset = max(0, len(data) - window)
        reported_indices = [index + index_offset for index in verdict.triggered_indices] if judge_every_point else []
        indices = self._clamp_indices(reported_indices, length=len(data))
        if not judge_every_point:
            # A live check judges one point, so a verdict about the latest point is the only
            # trigger that can fire — whatever else the model listed is history.
            indices = [len(data) - 1] if is_anomaly else []
        elif not is_anomaly:
            indices = []

        metadata: dict[str, Any] = {
            "rationale": verdict.rationale,
            "kind": verdict.kind,
            "model": LLM_DETECTOR_MODEL,
        }
        if verdict.is_anomaly and not confident:
            # Worth seeing in the check history: the model did flag something, the
            # confidence gate is what stopped the alert.
            metadata["below_threshold"] = True

        anomaly_score = self._anomaly_score(verdict)
        return DetectionResult(
            is_anomaly=is_anomaly,
            score=anomaly_score,
            triggered_indices=indices,
            all_scores=self._scores(anomaly_score, indices=indices, length=len(data))
            if judge_every_point
            else [anomaly_score],
            metadata=metadata,
        )

    @staticmethod
    def _anomaly_score(verdict: LLMDetectionVerdict) -> float:
        """The verdict as a probability of anomaly, which is the scale the threshold and the
        check history chart read scores on.

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
    def _scores(confidence: float, *, indices: list[int], length: int) -> list[float | None]:
        """One score per point for the simulation chart.

        The model reports a single confidence for the whole judgment rather than a score
        per point, so only the points it flagged carry one — the rest are left unscored
        instead of being given a made-up number.
        """
        flagged = set(indices)
        return [confidence if index in flagged else None for index in range(length)]

    @classmethod
    def get_default_config(cls) -> dict:
        return {
            "type": DetectorType.LLM.value,
            "threshold": DEFAULT_CONFIDENCE_THRESHOLD,
            "window": DEFAULT_WINDOW,
        }
