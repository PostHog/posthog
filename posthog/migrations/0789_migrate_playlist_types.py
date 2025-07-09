from django.db import migrations


def migrate_playlist_types(apps, schema_editor):
    # Bulk update every CHUNK_SIZE items
    CHUNK_SIZE = 100

    SessionRecordingPlaylist = apps.get_model("posthog", "SessionRecordingPlaylist")
    SessionRecordingPlaylistItem = apps.get_model("posthog", "SessionRecordingPlaylistItem")

    # 1. Get IDs of playlists that have playlist_items (should be COLLECTION)
    playlist_ids_with_items = (
        SessionRecordingPlaylistItem.objects.filter(playlist__type__isnull=True, playlist__deleted=False)
        .values_list("playlist_id", flat=True)
        .distinct()
    )

    # 2. Update playlists with items to COLLECTION type
    playlists_with_items = SessionRecordingPlaylist.objects.filter(
        id__in=playlist_ids_with_items, type__isnull=True, deleted=False
    )

    chunk = []
    for playlist in playlists_with_items.iterator(chunk_size=CHUNK_SIZE):
        playlist.type = "collection"
        chunk.append(playlist)

        # Bulk update every CHUNK_SIZE items
        if len(chunk) == CHUNK_SIZE:
            SessionRecordingPlaylist.objects.bulk_update(chunk, ["type"])
            chunk = []

    if chunk:  # Handle remaining items if length is less than CHUNK_SIZE
        SessionRecordingPlaylist.objects.bulk_update(chunk, ["type"])

    # 3. Update remaining playlists with null type to FILTERS type
    remaining_playlists = SessionRecordingPlaylist.objects.filter(type__isnull=True, deleted=False)

    chunk = []
    for playlist in remaining_playlists.iterator(chunk_size=CHUNK_SIZE):
        playlist.type = "filters"
        chunk.append(playlist)

        # Bulk update every CHUNK_SIZE items
        if len(chunk) == CHUNK_SIZE:
            SessionRecordingPlaylist.objects.bulk_update(chunk, ["type"])
            chunk = []

    if chunk:  # Handle remaining items if length is less than CHUNK_SIZE
        SessionRecordingPlaylist.objects.bulk_update(chunk, ["type"])


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0788_organization_members_can_create_personal_api_keys"),
    ]

    operations = [
        migrations.RunPython(migrate_playlist_types, reverse_code=migrations.RunPython.noop),
    ]
