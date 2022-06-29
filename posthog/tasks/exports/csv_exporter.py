import datetime
import gzip
import tempfile
import uuid
from typing import IO, Optional

import structlog
from sentry_sdk import capture_exception
from statshog.defaults.django import statsd

from posthog import settings
from posthog.celery import app
from posthog.models import Filter
from posthog.models.event.query_event_list import query_events_list
from posthog.models.exported_asset import ExportedAsset
from posthog.models.utils import UUIDT
from posthog.storage import object_storage

logger = structlog.get_logger(__name__)


def encode(obj: object) -> str:
    if isinstance(obj, uuid.UUID):
        return str(obj)

    if isinstance(obj, datetime.datetime):
        return obj.isoformat()

    return str(obj)


def stage_results_to_object_storage(
    day_filter: Filter, exported_asset: ExportedAsset, temporary_file: IO, write_headers: bool
) -> None:
    # load results
    result = query_events_list(
        filter=day_filter,
        team=exported_asset.team,
        request_get_query_dict=exported_asset.export_context.get("request_get_query_dict"),
        order_by=exported_asset.export_context.get("order_by"),
        action_id=exported_asset.export_context.get("action_id"),
        limit=100_000_000,  # what limit do we want?! None ¯\_(ツ)_/¯
    )
    if write_headers:
        temporary_file.write(f"{','.join(result[0].keys())}\n".encode("utf-8"))

    for values in [row.values() for row in result]:
        line = [encode(v) for v in values]
        temporary_file.write(",".join(line).encode("utf-8"))


def concat_results_in_object_storage(temporary_file: IO, exported_asset: ExportedAsset, root_bucket: str) -> str:
    object_path = f"/{root_bucket}/csvs/team-{exported_asset.team.id}/task-{exported_asset.id}/{UUIDT()}"
    temporary_file.seek(0)
    object_storage.write(object_path, gzip.compress(temporary_file.read()))
    return object_path


def _export_to_csv(exported_asset: ExportedAsset, root_bucket: str) -> None:
    if exported_asset.export_context.get("file_export_type", None) == "list_events":
        filter = Filter(data=exported_asset.export_context.get("filter"))

        write_headers = True
        with tempfile.TemporaryFile() as temporary_file:
            for day_filter in filter.split_by_day():
                stage_results_to_object_storage(day_filter, exported_asset, temporary_file, write_headers)
                write_headers = False

            object_path = concat_results_in_object_storage(temporary_file, exported_asset, root_bucket)
            exported_asset.content_location = object_path
            exported_asset.save(update_fields=["content_location", "export_context"])


@app.task()
def export_csv(exported_asset_id: int, root_bucket: str = settings.OBJECT_STORAGE_EXPORTS_FOLDER) -> None:
    timer = statsd.timer("csv_exporter").start()

    exported_asset: Optional[ExportedAsset] = None
    try:
        exported_asset = ExportedAsset.objects.get(pk=exported_asset_id)
        if exported_asset.export_format == "text/csv":
            _export_to_csv(exported_asset, root_bucket)
            statsd.incr("csv_exporter.succeeded", tags={"team_id": exported_asset.team.id})
        else:
            raise NotImplementedError(f"Export to format {exported_asset.export_format} is not supported")
    except Exception as e:
        if exported_asset:
            team_id = str(exported_asset.team.id)
        else:
            team_id = "unknown"
        capture_exception(e)
        statsd.incr("csv_exporter.failed", tags={"team_id": team_id})
    finally:
        timer.stop()
