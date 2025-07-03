from django.db import migrations
from posthog.session_recordings.models.session_recording_playlist import SessionRecordingPlaylist
from posthog.session_recordings.models.session_recording_playlist_item import SessionRecordingPlaylistItem


def migrate_playlist_types(apps, schema_editor):
    # 1. Get IDs of playlists that have playlist_items (should be COLLECTION)
    playlist_ids_with_items = (
        SessionRecordingPlaylistItem.objects.filter(playlist__type__isnull=True, playlist__deleted=False)
        .values_list("playlist_id", flat=True)
        .distinct()
    )

    # 2. Bulk update playlists with items to COLLECTION type
    SessionRecordingPlaylist.objects.filter(id__in=playlist_ids_with_items, type__isnull=True, deleted=False).update(
        type=SessionRecordingPlaylist.PlaylistType.COLLECTION
    )

    # 3. Bulk update remaining playlists with null type to FILTERS type
    SessionRecordingPlaylist.objects.filter(type__isnull=True, deleted=False).update(
        type=SessionRecordingPlaylist.PlaylistType.FILTERS
    )


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0784_fix_null_event_triggers"),
    ]

    operations = [
        migrations.RunPython(migrate_playlist_types, reverse_code=migrations.RunPython.noop),
    ]
