from django.db import migrations


def migrate_playlist_types(apps, schema_editor):
    SessionRecordingPlaylist = apps.get_model("posthog", "SessionRecordingPlaylist")
    SessionRecordingPlaylistItem = apps.get_model("posthog", "SessionRecordingPlaylistItem")

    # 1. Get IDs of playlists that have playlist_items (should be COLLECTION)
    playlist_ids_with_items = set(
        SessionRecordingPlaylistItem.objects.filter(playlist__type__isnull=True, playlist__deleted=False)
        .values_list("playlist_id", flat=True)
        .distinct()
    )

    # 2. Update playlists with items to COLLECTION type using chunking
    playlists_with_items = SessionRecordingPlaylist.objects.filter(
        id__in=playlist_ids_with_items, type__isnull=True, deleted=False
    )

    for playlist in playlists_with_items.iterator(chunk_size=100):
        playlist.type = "collection"
        playlist.save(update_fields=["type"])

    # 3. Update remaining playlists with null type to FILTERS type using chunking
    remaining_playlists = SessionRecordingPlaylist.objects.filter(type__isnull=True, deleted=False)

    for playlist in remaining_playlists.iterator(chunk_size=100):
        playlist.type = "filters"
        playlist.save(update_fields=["type"])


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0785_team_drop_events_older_than_seconds"),
    ]

    operations = [
        migrations.RunPython(migrate_playlist_types, reverse_code=migrations.RunPython.noop),
    ]
