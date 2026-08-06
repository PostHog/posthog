"""Temporal pipeline that writes surfacing scores onto session_replay_events.

See README.md in this directory for the architecture rationale.
"""

from posthog.temporal.session_replay.surfacing_scoring_sweep.activities import (
    list_chunks_activity,
    score_chunk_activity,
)
from posthog.temporal.session_replay.surfacing_scoring_sweep.workflow import ScoreSessionsBatchWorkflow

SURFACING_SCORING_SWEEP_WORKFLOWS = [ScoreSessionsBatchWorkflow]
SURFACING_SCORING_SWEEP_ACTIVITIES = [list_chunks_activity, score_chunk_activity]
