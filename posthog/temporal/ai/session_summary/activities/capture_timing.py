from dataclasses import dataclass
from typing import Literal

import temporalio

from posthog.models import Team

from ee.hogai.session_summaries.tracking import capture_session_summary_timing


@dataclass
class CaptureTimingInputs:
    distinct_id: str | None
    team_id: int
    session_id: str
    timing_type: Literal["video_render", "transcript", "single_session_flow", "group_session_flow"]
    duration_seconds: float
    success: bool
    extra_properties: dict | None = None


@temporalio.activity.defn
async def capture_timing_activity(inputs: CaptureTimingInputs) -> None:
    team = await Team.objects.aget(id=inputs.team_id)
    capture_session_summary_timing(
        user_distinct_id=inputs.distinct_id,
        team=team,
        session_id=inputs.session_id,
        timing_type=inputs.timing_type,
        duration_seconds=inputs.duration_seconds,
        success=inputs.success,
        extra_properties=inputs.extra_properties,
    )
