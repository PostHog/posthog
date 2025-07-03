from celery import shared_task
import structlog
from django.db import transaction
from posthog.session_recordings.models.session_recording_playlist import SessionRecordingPlaylist
from posthog.tasks.utils import CeleryQueue

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value, max_retries=3)
def migrate_playlist_type(dry_run: bool = False) -> None:
    """
    One-time migration task to set type field on SessionRecordingPlaylist records.
    Sets type to 'collection' if playlist has recordings, 'filters' if empty.

    Args:
        dry_run: If True, will not actually perform the migration, but will print out what would have been done
    """
    mode = "DRY RUN" if dry_run else "LIVE"
    logger.info("Starting playlist type migration", mode=mode, dry_run=dry_run)

    # Get all playlists that don't have a type
    playlists_to_update = (
        SessionRecordingPlaylist.objects.filter(type__isnull=True, deleted=False)
        .select_related()
        .prefetch_related("playlist_items")
    )

    total_count = playlists_to_update.count()
    logger.info(f"Found {total_count} playlists to update")

    if total_count == 0:
        logger.info("No playlists to update")
        return

    updated_collection_count = 0
    updated_filters_count = 0

    try:
        if dry_run:
            logger.info("Running in dry run mode, would have updated the following playlists:")
            for playlist in playlists_to_update:
                if playlist.playlist_items.exists():
                    updated_collection_count += 1
                else:
                    updated_filters_count += 1
                logger.info(f"Would have updated playlist {playlist.id} to {playlist.type}")
        else:
            logger.info("Running in live mode, updating playlists...")
            with transaction.atomic():
                for playlist in playlists_to_update:
                    if playlist.playlist_items.exists():
                        playlist.type = SessionRecordingPlaylist.PlaylistType.COLLECTION
                        updated_collection_count += 1
                    else:
                        playlist.type = SessionRecordingPlaylist.PlaylistType.FILTERS
                        updated_filters_count += 1
                    playlist.save(update_fields=["type"])

        logger.info(
            "Playlist type migration completed successfully",
            total_updated=updated_collection_count + updated_filters_count,
            collection_count=updated_collection_count,
            filters_count=updated_filters_count,
        )

    except Exception as e:
        logger.exception(f"Error updating playlist type: {e}")
        raise
