from celery import shared_task
from celery.app.task import Task
from posthog.models import Team, User
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.session_recordings.models.session_recording_playlist_item import SessionRecordingPlaylistItem
from posthog.schema import RecordingsQuery
from posthog.event_usage import report_user_action
import structlog
from typing import Any

logger = structlog.get_logger(__name__)


@shared_task(bind=True)
def bulk_delete_recordings_task(
    self: Task, team_id: int, user_id: int, filters: dict[str, Any], user_distinct_id: str
) -> dict[str, Any]:
    """
    Bulk delete recordings matching the provided filters.
    Also mark associated playlist items as deleted.
    Processed in batches to avoid memory issues.
    """
    from posthog.session_recordings.session_recording_api import list_recordings_from_query

    try:
        team = Team.objects.get(id=team_id)
        user = User.objects.get(id=user_id)
        query = RecordingsQuery.model_validate(filters)

        CHUNK_SIZE = 100
        deleted_count = 0
        playlist_items_deleted_count = 0
        offset = 0

        # Process recordings in chunks using database pagination
        while True:
            # Set pagination for this chunk
            query.limit = CHUNK_SIZE
            query.offset = offset

            # Get chunk of recordings
            chunk_recordings, _, _ = list_recordings_from_query(query, user, team)

            if not chunk_recordings:
                break  # No more recordings to process

            session_ids_chunk = [str(r.session_id) for r in chunk_recordings]

            # 1. Update existing Postgres SessionRecording records
            SessionRecording.objects.filter(team=team, session_id__in=session_ids_chunk).update(deleted=True)

            # 2. Create recording for ClickHouse-only recordings
            existing_session_ids = set(
                SessionRecording.objects.filter(team=team, session_id__in=session_ids_chunk).values_list(
                    "session_id", flat=True
                )
            )

            recordings_to_create = []
            for recording in chunk_recordings:
                if recording.session_id not in existing_session_ids:
                    recordings_to_create.append(
                        SessionRecording(
                            team=team, session_id=recording.session_id, distinct_id=recording.distinct_id, deleted=True
                        )
                    )

            if recordings_to_create:
                SessionRecording.objects.bulk_create(recordings_to_create)

            # 3. Update associated playlist items
            playlist_items_updated = SessionRecordingPlaylistItem.objects.filter(
                playlist__team=team, recording__in=session_ids_chunk
            ).update(deleted=True)

            deleted_count += len(chunk_recordings)
            playlist_items_deleted_count += playlist_items_updated
            offset += CHUNK_SIZE

            # Update progress
            self.update_state(
                state="PROGRESS",
                meta={
                    "current": deleted_count,
                    "total": "unknown",  # We don't know total upfront with streaming
                    "playlist_items_deleted": playlist_items_deleted_count,
                    "status": f"Processed {deleted_count} recordings, {playlist_items_deleted_count} playlist items deleted",
                },
            )

            logger.info(
                "bulk_delete_recordings_task_progress",
                team_id=team_id,
                user_id=user_id,
                current=deleted_count,
                playlist_items_deleted=playlist_items_deleted_count,
            )

        # Log completion
        report_user_action(
            user=user,
            event="bulk_delete_recordings",
            properties={
                "team_id": team_id,
                "user_id": user_id,
                "filters": filters,
                "user_distinct_id": user_distinct_id,
                "deleted_count": deleted_count,
                "playlist_items_deleted_count": playlist_items_deleted_count,
            },
            team=team,
        )
        logger.info(
            "bulk_delete_recordings_task_completed",
            team_id=team_id,
            user_id=user_id,
            deleted_count=deleted_count,
            playlist_items_deleted=playlist_items_deleted_count,
        )

        return {
            "deleted_count": deleted_count,
            "playlist_items_deleted_count": playlist_items_deleted_count,
            "message": f"Successfully deleted {deleted_count} recordings and {playlist_items_deleted_count} playlist items",
        }

    except Exception as e:
        logger.exception(f"Error in bulk_delete_recordings_task: {e}")
        raise
