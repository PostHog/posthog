from django.db import migrations, transaction
from django.db.models import Q


def _without_retired_fields(filters: dict) -> dict:
    cleaned = {key: value for key, value in filters.items() if key != "recommended_only"}
    if cleaned.get("order") == "surfacing_score":
        cleaned.pop("order")
    return cleaned


# A saved `order` the recordings query no longer accepts would fail validation, so dropping it falls back to the
# default order. Each row is re-read under its own row lock, so an edit a user makes while this runs is kept.
def drop_retired_relevance_filters(apps, schema_editor):
    SessionRecordingPlaylist = apps.get_model("posthog", "SessionRecordingPlaylist")
    retired = Q(filters__order="surfacing_score") | Q(filters__has_key="recommended_only")
    ids = list(SessionRecordingPlaylist._base_manager.filter(retired).values_list("id", flat=True))
    for playlist_id in ids:
        with transaction.atomic():
            playlist = (
                SessionRecordingPlaylist._base_manager.select_for_update().filter(retired, id=playlist_id).first()
            )
            if playlist is None:
                continue
            playlist.filters = _without_retired_fields(playlist.filters)
            playlist.save(update_fields=["filters"])


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1435_ema_issuer_management"),
    ]

    operations = [
        migrations.RunPython(drop_retired_relevance_filters, migrations.RunPython.noop, elidable=True),
    ]
