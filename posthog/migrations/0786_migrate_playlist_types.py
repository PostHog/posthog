from django.db import migrations


def migrate_playlist_types(apps, schema_editor):
    SessionRecordingPlaylist = apps.get_model("posthog", "SessionRecordingPlaylist")
    SessionRecordingPlaylistItem = apps.get_model("posthog", "SessionRecordingPlaylistItem")

    # 1. Get IDs of playlists that have playlist_items (should be COLLECTION)
    playlist_ids_with_items = (
        SessionRecordingPlaylistItem.objects.filter(playlist__type__isnull=True, playlist__deleted=False)
        .values_list("playlist_id", flat=True)
        .distinct()
    )

    # 2. Bulk update playlists with items to COLLECTION type
    SessionRecordingPlaylist.objects.filter(id__in=playlist_ids_with_items, type__isnull=True, deleted=False).update(
        type="collection"  # Use string value instead of enum
    )

    # 3. Bulk update remaining playlists with null type to FILTERS type
    SessionRecordingPlaylist.objects.filter(type__isnull=True, deleted=False).update(
        type="filters"  # Use string value instead of enum
    )


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0785_team_drop_events_older_than_seconds"),
    ]

    operations = [
        migrations.RunPython(migrate_playlist_types, reverse_code=migrations.RunPython.noop),
    ]
