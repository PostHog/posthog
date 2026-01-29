from typing import Literal
from uuid import uuid4

import posthoganalytics

from posthog.event_usage import groups
from posthog.models import Team, User

SummarySource = Literal["chat", "api"]
SummaryType = Literal["single", "group"]


def capture_session_summary_started(
    *,
    user: User,
    team: Team,
    tracking_id: str,
    summary_source: SummarySource,
    summary_type: SummaryType,
    is_streaming: bool,
    session_ids: list[str],
    video_validation_enabled: bool | Literal["full"] | None,
) -> None:
    """Capture the start of a session summary generation."""
    if not user.distinct_id:
        return
    posthoganalytics.capture(
        distinct_id=user.distinct_id,
        event="session summary started",
        properties={
            "tracking_id": tracking_id,
            "summary_source": summary_source,
            "summary_type": summary_type,
            "is_streaming": is_streaming,
            "session_ids": session_ids,
            "session_count": len(session_ids),
            "video_validation_enabled": video_validation_enabled,
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
    is_streaming: bool,
    session_ids: list[str],
    video_validation_enabled: bool | Literal["full"] | None,
    success: bool | None,
    error_type: str | None = None,
    error_message: str | None = None,
) -> None:
    """Capture the completion of a session summary generation."""
    if not user.distinct_id:
        return
    properties: dict = {
        "tracking_id": tracking_id,
        "summary_source": summary_source,
        "summary_type": summary_type,
        "is_streaming": is_streaming,
        "session_ids": session_ids,
        "session_count": len(session_ids),
        "video_validation_enabled": video_validation_enabled,
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
