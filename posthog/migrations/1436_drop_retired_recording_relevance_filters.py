from django.db import migrations
from django.db.models import Q


# A saved `order` the recordings query no longer accepts would fail validation, so dropping it
# falls back to the default order.
def drop_retired_relevance_filters(apps, schema_editor):
    SessionRecordingPlaylist = apps.get_model("posthog", "SessionRecordingPlaylist")
    rows = SessionRecordingPlaylist._base_manager.filter(
        Q(filters__order="surfacing_score") | Q(filters__has_key="recommended_only")
    )
    for playlist in rows.only("id", "filters").iterator(chunk_size=500):
        filters = dict(playlist.filters)
        filters.pop("recommended_only", None)
        if filters.get("order") == "surfacing_score":
            filters.pop("order")
        playlist.filters = filters
        playlist.save(update_fields=["filters"])


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1435_ema_issuer_management"),
    ]

    operations = [
        migrations.RunPython(drop_retired_relevance_filters, migrations.RunPython.noop, elidable=True),
    ]
