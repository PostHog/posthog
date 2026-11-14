from django.db import migrations, transaction
from django.db.models import Q


def _without_retired_fields(filters: dict) -> dict:
    cleaned = {key: value for key, value in filters.items() if key != "recommended_only"}
    if cleaned.get("order") == "surfacing_score":
        cleaned.pop("order")
    return cleaned


# A saved `order` the recordings query no longer accepts would fail validation, so dropping it falls back to the
# default order. Each row is re-read and saved in its own short transaction, so an edit a user makes while this runs is
# kept and no lock outlives its row. Re-running skips rows already cleaned, so a retry after a partial run is safe.
def drop_retired_relevance_filters(apps, schema_editor):
    alias = schema_editor.connection.alias
    playlists = apps.get_model("posthog", "SessionRecordingPlaylist")._base_manager.using(alias)
    retired = Q(filters__order="surfacing_score") | Q(filters__has_key="recommended_only")
    for playlist_id in list(playlists.filter(retired).values_list("id", flat=True)):
        with transaction.atomic(using=alias):
            playlist = playlists.select_for_update().filter(retired, id=playlist_id).first()
            # Filters are free-form JSON, so a non-object value is left alone rather than failing the deploy.
            if playlist is None or not isinstance(playlist.filters, dict):
                continue
            playlist.filters = _without_retired_fields(playlist.filters)
            playlist.save(update_fields=["filters"])


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "1435_ema_issuer_management"),
    ]

    operations = [
        migrations.RunPython(drop_retired_relevance_filters, migrations.RunPython.noop, elidable=True),
    ]
