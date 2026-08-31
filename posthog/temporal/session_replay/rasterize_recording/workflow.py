import datetime as dt
from typing import Any

import temporalio.workflow as wf
from temporalio import common
from temporalio.exceptions import (
    FailureError,
    TimeoutError as TemporalTimeoutError,
)

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.search_attributes import POSTHOG_SESSION_RECORDING_ID_KEY, POSTHOG_TEAM_ID_KEY

with wf.unsafe.imports_passed_through():
    from django.conf import settings

    from prometheus_client import Counter

    RASTERIZATION_COMPLETED_COUNTER = Counter(
        "posthog_rasterization_completed",
        "Rasterization completions by product and task queue",
        ["product", "task_queue"],
    )

    RASTERIZATION_FAILED_COUNTER = Counter(
        "posthog_rasterization_failed",
        "Rasterization workflow failures by product and task queue",
        ["product", "task_queue"],
    )

from posthog.temporal.common.errors import (
    MAX_ERROR_MESSAGE_CHARS,
    resolve_exception_class,
    truncate_for_temporal_payload,
    unwrap_temporal_cause,
)

from .activities import (
    BumpStuckCounterInput,
    build_rasterization_input,
    bump_stuck_counter_activity,
    clear_stuck_counter_activity,
    finalize_rasterization,
    record_rasterization_failure,
)
from .types import (
    RASTERIZE_RENDER_MAX_ATTEMPTS,
    RASTERIZE_RENDER_TIMEOUT,
    BuildRasterizationResult,
    FinalizeRasterizationInput,
    RasterizationActivityOutput,
    RasterizeRecordingInputs,
    RecordRasterizationFailureInput,
)

# Gates the failure-recording activity added to the except branch. In-flight executions recorded
# their history without it, so replaying them against an unconditional call fails as non-determinism.
_RECORD_FAILURE_PATCH = "rasterize-record-failure-2026-08"


def _resolve_error_code(exc: BaseException) -> str:
    """The code recorded onto the asset when the renderer produced none of its own.

    A render activity killed by a heartbeat or start-to-close timeout (lost or wedged worker) has no
    ApplicationError in its cause chain, only Temporal's TimeoutError — without this check it would
    classify as an opaque `ActivityError` and land in the unknown bucket.
    """
    current: BaseException | None = exc
    while isinstance(current, FailureError):
        if isinstance(current, TemporalTimeoutError):
            return "ACTIVITY_TIMEOUT"
        current = current.cause
    return resolve_exception_class(exc)


def _record_outcome(counter: Counter, inputs: RasterizeRecordingInputs) -> None:
    if wf.unsafe.is_replaying():
        return
    counter.labels(product=inputs.product, task_queue=wf.info().task_queue).inc()


@wf.defn(name="rasterize-recording")
class RasterizeRecordingWorkflow(PostHogWorkflow):
    inputs_cls = RasterizeRecordingInputs

    def __init__(self) -> None:
        self._phase: str = "preparing"

    @wf.query
    def get_progress(self) -> dict[str, str]:
        """Frame-level progress lives in the activity heartbeat, not here."""
        return {"phase": self._phase}

    @wf.run
    async def run(self, inputs: RasterizeRecordingInputs) -> RasterizationActivityOutput:
        try:
            result = await self._run(inputs)
        except Exception as exc:
            # Resolved once so the recorded code and the quarantine decision cannot drift apart.
            error_code = _resolve_error_code(exc)
            # Count runs, not attempts: only the final scheduled attempt is a failed run.
            if self._is_final_attempt():
                _record_outcome(RASTERIZATION_FAILED_COUNTER, inputs)
                if wf.patched(_RECORD_FAILURE_PATCH):
                    await self._record_failure(inputs, exc, error_code)
            await self._maybe_bump_stuck_counter(error_code)
            raise
        await self._maybe_clear_stuck_counter()
        _record_outcome(RASTERIZATION_COMPLETED_COUNTER, inputs)
        return result

    @staticmethod
    def _max_attempts() -> int | None:
        retry_policy = wf.info().retry_policy
        return retry_policy.maximum_attempts if retry_policy else 1

    @classmethod
    def _is_final_attempt(cls) -> bool:
        max_attempts = cls._max_attempts()
        return max_attempts is not None and 0 < max_attempts <= wf.info().attempt

    async def _record_failure(self, inputs: RasterizeRecordingInputs, exc: BaseException, error_code: str) -> None:
        """Write the renderer's own reason onto the asset before the workflow fails.

        Swallows its own errors: losing the reason is worse than the render failing, but masking the
        render's failure would be worse still.
        """
        cause = unwrap_temporal_cause(exc) or exc
        try:
            await wf.execute_activity(
                record_rasterization_failure,
                RecordRasterizationFailureInput(
                    exported_asset_id=inputs.exported_asset_id,
                    error_code=error_code,
                    error_message=truncate_for_temporal_payload(str(cause), MAX_ERROR_MESSAGE_CHARS),
                ),
                start_to_close_timeout=dt.timedelta(seconds=30),
                retry_policy=common.RetryPolicy(maximum_attempts=3),
            )
        except Exception as record_exc:
            wf.logger.warning("rasterize.record_failure_failed", extra={"error": str(record_exc)})

    async def _maybe_bump_stuck_counter(self, error_code: str) -> None:
        info = wf.info()
        max_attempts = self._max_attempts()
        # Bump only on the final scheduled attempt; recoverable failures would otherwise over-count.
        if max_attempts is None or max_attempts <= 0:
            wf.logger.warning(
                "rasterize.stuck_counter_skipped_no_max_attempts",
                extra={"max_attempts": max_attempts, "attempt": info.attempt},
            )
            return
        if info.attempt < max_attempts:
            return
        session_id = info.typed_search_attributes.get(POSTHOG_SESSION_RECORDING_ID_KEY)
        team_id = info.typed_search_attributes.get(POSTHOG_TEAM_ID_KEY)
        if session_id is None or team_id is None:
            return
        # A timeout-class final failure during the render phase means the worker died mid-render
        # (OOM, wedge): the recording already took a pod down, so it quarantines at once instead of
        # after a second envelope. The phase guard keeps a timed-out prep or finalize activity (a
        # Postgres incident, not the recording) on the ordinary two-strike path.
        killed_worker = error_code == "ACTIVITY_TIMEOUT" and self._phase == "rendering"
        try:
            await wf.execute_activity(
                bump_stuck_counter_activity,
                BumpStuckCounterInput(team_id=team_id, session_id=session_id, killed_worker=killed_worker),
                start_to_close_timeout=dt.timedelta(seconds=10),
                retry_policy=common.RetryPolicy(maximum_attempts=2),
            )
        except Exception as exc:
            wf.logger.warning("rasterize.stuck_counter_bump_failed", extra={"error": str(exc)})

    async def _maybe_clear_stuck_counter(self) -> None:
        info = wf.info()
        session_id = info.typed_search_attributes.get(POSTHOG_SESSION_RECORDING_ID_KEY)
        team_id = info.typed_search_attributes.get(POSTHOG_TEAM_ID_KEY)
        if session_id is None or team_id is None:
            return
        try:
            await wf.execute_activity(
                clear_stuck_counter_activity,
                BumpStuckCounterInput(team_id=team_id, session_id=session_id),
                start_to_close_timeout=dt.timedelta(seconds=10),
                retry_policy=common.RetryPolicy(maximum_attempts=2),
            )
        except Exception as exc:
            wf.logger.warning("rasterize.stuck_counter_clear_failed", extra={"error": str(exc)})

    async def _run(self, inputs: RasterizeRecordingInputs) -> RasterizationActivityOutput:
        retry_policy = common.RetryPolicy(maximum_attempts=3)

        self._phase = "preparing"
        prep: BuildRasterizationResult = await wf.execute_activity(
            build_rasterization_input,
            inputs.exported_asset_id,
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=retry_policy,
        )

        if prep.cached_output is not None:
            self._phase = "done"
            return prep.cached_output

        assert prep.activity_input is not None  # tagged-union invariant

        self._phase = "rendering"
        # Plain dict from Node.js across the cross-language boundary.
        raw_result: dict[str, Any] = await wf.execute_activity(
            "rasterize-recording",
            prep.activity_input.model_dump(exclude_none=True),
            # Reading a Django setting inside a workflow body is normally banned (it is not part of
            # recorded history); it is tolerated here because Temporal does not replay-check the
            # task-queue attribute, and a mid-flight change only redirects retries.
            task_queue=settings.RASTERIZATION_TASK_QUEUE,
            start_to_close_timeout=RASTERIZE_RENDER_TIMEOUT,
            heartbeat_timeout=dt.timedelta(seconds=30),
            retry_policy=common.RetryPolicy(maximum_attempts=RASTERIZE_RENDER_MAX_ATTEMPTS),
        )

        result = RasterizationActivityOutput.model_validate(raw_result)

        self._phase = "finalizing"
        await wf.execute_activity(
            finalize_rasterization,
            FinalizeRasterizationInput(
                exported_asset_id=inputs.exported_asset_id,
                result=result,
                render_fingerprint=prep.render_fingerprint,
            ),
            start_to_close_timeout=dt.timedelta(minutes=2),
            retry_policy=retry_policy,
        )

        self._phase = "done"
        return result
