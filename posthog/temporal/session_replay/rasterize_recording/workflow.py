import datetime as dt
from typing import Any

import temporalio.workflow as wf
from temporalio import common

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.search_attributes import POSTHOG_SESSION_RECORDING_ID_KEY, POSTHOG_TEAM_ID_KEY

with wf.unsafe.imports_passed_through():
    from django.conf import settings

from .activities import (
    BumpStuckCounterInput,
    build_rasterization_input,
    bump_stuck_counter_activity,
    clear_stuck_counter_activity,
    finalize_rasterization,
)
from .types import (
    BuildRasterizationResult,
    FinalizeRasterizationInput,
    RasterizationActivityOutput,
    RasterizeRecordingInputs,
)


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
        except Exception:
            await self._maybe_bump_stuck_counter()
            raise
        await self._maybe_clear_stuck_counter()
        return result

    async def _maybe_bump_stuck_counter(self) -> None:
        info = wf.info()
        retry_policy = info.retry_policy
        max_attempts = retry_policy.maximum_attempts if retry_policy else 1
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
        try:
            await wf.execute_activity(
                bump_stuck_counter_activity,
                BumpStuckCounterInput(team_id=team_id, session_id=session_id),
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
            task_queue=settings.RASTERIZATION_TASK_QUEUE,
            start_to_close_timeout=dt.timedelta(minutes=30),
            heartbeat_timeout=dt.timedelta(seconds=30),
            retry_policy=common.RetryPolicy(maximum_attempts=2),
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
