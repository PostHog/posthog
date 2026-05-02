from typing import Literal
from uuid import uuid4

import posthoganalytics

from posthog.event_usage import groups
from posthog.models import Team, User

SummarySource = Literal["chat", "api", "dock"]
SummaryType = Literal["single", "group"]


def capture_session_summary_timing(
    *,
    user_distinct_id: str | None,
    team: Team,
    session_id: str,
    timing_type: Literal["single_session_flow", "group_session_flow"],
    duration_seconds: float,
    success: bool,
    extra_properties: dict | None = None,
) -> None:
    if not user_distinct_id:
        return
    properties: dict = {
        "ai_product": "session_replay",
        "session_id": session_id,
        "timing_type": timing_type,
        "duration_seconds": duration_seconds,
        "success": success,
    }
    if extra_properties:
        properties.update(extra_properties)
    posthoganalytics.capture(
        distinct_id=user_distinct_id,
        event="session summary timing",
        properties=properties,
        groups=groups(None, team),
    )


def capture_session_summary_started(
    *,
    user: User,
    team: Team,
    tracking_id: str,
    summary_source: SummarySource,
    summary_type: SummaryType,
    session_ids: list[str],
    video_based: bool = False,
) -> None:
    """Capture the start of a session summary generation."""
    if not user.distinct_id:
        return
    posthoganalytics.capture(
        distinct_id=user.distinct_id,
        event="session summary started",
        properties={
            "ai_product": "session_replay",
            "tracking_id": tracking_id,
            "summary_source": summary_source,
            "summary_type": summary_type,
            "session_ids": session_ids,
            "session_count": len(session_ids),
            "video_based": video_based,
        },
        # The org id will be fetched from the team without need to pull the organization from the user (annoying in async context)
        groups=groups(None, team),
    )


def capture_session_summary_generated(
    *,
    user: User,
    team: Team,
    tracking_id: str,
    summary_source: SummarySource,
    summary_type: SummaryType,
    session_ids: list[str],
    video_based: bool = False,
    success: bool | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
) -> None:
    """Capture the completion of a session summary generation."""
    if not user.distinct_id:
        return
    properties: dict = {
        "ai_product": "session_replay",
        "tracking_id": tracking_id,
        "summary_source": summary_source,
        "summary_type": summary_type,
        "session_ids": session_ids,
        "session_count": len(session_ids),
        "video_based": video_based,
        "success": success,
    }
    if error_type is not None:
        properties["error_type"] = error_type
    if error_message is not None:
        properties["error_message"] = error_message
    posthoganalytics.capture(
        distinct_id=user.distinct_id,
        event="session summary generated",
        properties=properties,
        groups=groups(None, team),
    )


def generate_tracking_id() -> str:
    """Generate a unique tracking ID for correlating started/generated events."""
    return str(uuid4())
