from celery import shared_task
from posthog.models import Team, User
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.session_recordings.models.session_recording_playlist_item import SessionRecordingPlaylistItem
from posthog.session_recordings.session_recording_api import list_recordings_from_query
from posthog.schema import RecordingsQuery
from posthog.event_usage import report_user_action
import structlog

logger = structlog.get_logger(__name__)


@shared_task
def bulk_delete_recordings_task(self, team_id: int, user_id: int, filters: dict, user_distinct_id: str):
    """
    Bulk delete recordings matching the provided filters.
    Also mark associated playlist items as deleted.
    Processed in batches of 100 recordings to avoid memory issues.
    """
    try:
        team = Team.objects.get(id=team_id)
        user = User.objects.get(id=user_id)
        query = RecordingsQuery.model_validate(filters)

        # We need to remove pagination as it's a bulk operation
        query.limit = None
        query.offset = None

        # Get all matching recordings
        recordings, _, _ = list_recordings_from_query(query, user, team)

        if not recordings:
            return {"deleted_count": 0, "message": "No recordings found matching the provided filters"}
        total_recordings = len(recordings)
        CHUNK_SIZE = 100
        deleted_count = 0
        playlist_items_deleted_count = 0

        # Process in chunks to avoid memory issues
        for i in range(0, total_recordings, CHUNK_SIZE):
            chunk = recordings[i : i + CHUNK_SIZE]
            session_ids_chunk = [str(r.session_id) for r in chunk]

            # 1. Update existing Postgres SessionRecording records
            SessionRecording.objects.filter(team=team, session_id__in=session_ids_chunk).update(deleted=True)

            # 2. Create recording for ClickHouse-only recordings
            existing_session_ids = set(
                SessionRecording.objects.filter(team=team, session_id__in=session_ids_chunk).values_list(
                    "session_id", flat=True
                )
            )

            recordings_to_create = []
            for recording in chunk:
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
                playlist__team=team, recording_id__in=session_ids_chunk
            ).update(deleted=True)

            deleted_count += len(chunk)
            playlist_items_deleted_count += playlist_items_updated

            # Update progress
            self.update_state(
                state="PROGRESS",
                meta={
                    "current": deleted_count,
                    "total": total_recordings,
                    "playlist_items_deleted": playlist_items_deleted_count,
                    "status": f"Processed {deleted_count} of {total_recordings} recordings, {playlist_items_deleted_count} playlist items deleted",
                },
            )

            logger.info(
                "bulk_delete_recordings_task_progress",
                team_id=team_id,
                user_id=user_id,
                current=deleted_count,
                total=total_recordings,
                playlist_items_deleted=playlist_items_deleted_count,
            )

        # Log completion (I think this is important as it's a delete operation)
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
            current=deleted_count,
            total=total_recordings,
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
