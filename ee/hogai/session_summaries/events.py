from typing import Literal

from django.conf import settings

import structlog

from posthog.api.capture import capture_internal

from ee.models.session_summaries import SingleSessionSummary

EVENT_SOURCE = "session_summary_events"
SummaryOrigin = Literal["single", "group"]
logger = structlog.get_logger(__name__)


def _build_replay_url(summary: SingleSessionSummary) -> str:
    return f"{settings.SITE_URL.rstrip('/')}/project/{summary.team_id}/replay/{summary.session_id}"


def capture_session_summary_ready(
    summary: SingleSessionSummary,
    *,
    summary_origin: SummaryOrigin,
    team_api_token: str,
) -> None:
    summary_context = summary.extra_summary_context
    summary_content = summary.summary
    run_metadata = summary.run_metadata or {}
    try:
        response = capture_internal(
            token=team_api_token,
            event_name="$session_summary_ready",
            event_source=EVENT_SOURCE,
            distinct_id=summary.distinct_id or f"session_summary:{summary.team_id}:{summary.session_id}",
            timestamp=summary.created_at,
            properties={
                "$insert_id": str(summary.id),
                "session_id": summary.session_id,
                "team_id": summary.team_id,
                "summary_id": str(summary.id),
                "summary_origin": summary_origin,
                "session_summary": summary_content,
                "extra_summary_context": summary_context,
                "session_summary_focus_area": summary_context.get("focus_area") if summary_context else None,
                "replay_url": _build_replay_url(summary),
                "visual_confirmation": bool(run_metadata.get("visual_confirmation", False)),
                "model_used": run_metadata.get("model_used"),
                "session_start_time": summary.session_start_time.isoformat() if summary.session_start_time else None,
                "session_duration": summary.session_duration,
            },
        )
        response.raise_for_status()
    except Exception:
        logger.exception(
            "failed_to_capture_session_summary_ready",
            summary_id=str(summary.id),
            session_id=summary.session_id,
            team_id=summary.team_id,
            summary_origin=summary_origin,
        )
