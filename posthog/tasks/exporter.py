from posthog.celery import app
from posthog.models import ExportedAsset


@app.task()
def export_asset(exported_asset_id: int) -> None:
    from statshog.defaults.django import statsd

    from posthog import settings
    from posthog.tasks.exports import csv_exporter, insight_exporter

    exported_asset = ExportedAsset.objects.select_related("insight", "dashboard").get(pk=exported_asset_id)

    is_csv_export = exported_asset.export_format == ExportedAsset.ExportFormat.CSV
    if is_csv_export:
        csv_exporter.export_csv(exported_asset, settings.OBJECT_STORAGE_EXPORTS_FOLDER)
        statsd.incr("csv_exporter.queued", tags={"team_id": str(exported_asset.team_id)})
    else:
        insight_exporter.export_insight(exported_asset)
        statsd.incr("insight_exporter.queued", tags={"team_id": str(exported_asset.team_id)})
