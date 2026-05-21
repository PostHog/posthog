from django.conf import settings

import structlog

from posthog.api.capture import capture_internal
from posthog.temporal.session_replay.session_summary.types.events import SessionSummaryReadyProperties

from ee.models.session_summaries import SingleSessionSummary

EVENT_SOURCE = "session_summary_events"
logger = structlog.get_logger(__name__)


def _build_replay_url(summary: SingleSessionSummary) -> str:
    return f"{settings.SITE_URL.rstrip('/')}/project/{summary.team_id}/replay/{summary.session_id}"


def capture_session_summary_ready(
    summary: SingleSessionSummary,
    *,
    team_api_token: str,
) -> None:
    summary_context = summary.extra_summary_context
    run_metadata = summary.run_metadata or {}
    properties = SessionSummaryReadyProperties(
        insert_id=str(summary.id),
        session_id=summary.session_id,
        team_id=summary.team_id,
        summary_id=str(summary.id),
        session_summary=summary.summary,
        extra_summary_context=summary_context,
        session_summary_focus_area=summary_context.get("focus_area") if summary_context else None,
        replay_url=_build_replay_url(summary),
        model_used=run_metadata.get("model_used"),
        session_start_time=summary.session_start_time,
        session_duration=summary.session_duration,
    )
    try:
        response = capture_internal(
            token=team_api_token,
            event_name="$session_summary_ready",
            event_source=EVENT_SOURCE,
            distinct_id=summary.distinct_id or f"session_summary:{summary.team_id}:{summary.session_id}",
            timestamp=summary.created_at,
            properties=properties.model_dump(by_alias=True, mode="json"),
        )
        response.raise_for_status()
    except Exception:
        logger.exception(
            "failed_to_capture_session_summary_ready",
            summary_id=str(summary.id),
            session_id=summary.session_id,
            team_id=summary.team_id,
        )
