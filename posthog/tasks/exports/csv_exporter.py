import datetime
import gzip
import tempfile
import uuid
from typing import IO, List

import requests
import structlog
from sentry_sdk import capture_exception, push_scope
from statshog.defaults.django import statsd

from posthog import settings
from posthog.jwt import PosthogJwtAudience, encode_jwt
from posthog.models import Filter
from posthog.models.event.query_event_list import query_events_list
from posthog.models.exported_asset import ExportedAsset
from posthog.models.utils import UUIDT
from posthog.storage import object_storage
from posthog.utils import absolute_uri

logger = structlog.get_logger(__name__)


# SUPPORTED CSV TYPES

## Insights - Trends (Series Linear, Series Cumulative, Totals)
# Funnels - steps as data
# Retention
# Paths
# Lifecycle
# Via dashboard e.g. all of the above

## People
# Cohorts
# Retention
# Funnel

## Events
# Filtered

### HOW DOES THIS WORK
# 1. We receive an export task with a given resource uri (identical to the API)
# 2. We call the actual API to load the data with the given params so that we receive a paginateable response
# 3. We save the response to a chunk in object storage and then load the `next` page of results
# 4. Repeat until exhausted or limit reached
# 5. We save the final blob output and update the ExportedAsset
# TRICKY: How to do auth with the API?
# TRICKY: Can we bypass the API and use the raw ViewSets


def quote(s: str) -> str:
    escaped = s.replace('"', '""')
    return f'"{escaped}"'


def encode(obj: object) -> str:
    if isinstance(obj, uuid.UUID):
        return quote(str(obj))

    if isinstance(obj, datetime.datetime):
        return quote(obj.isoformat())

    return quote(str(obj))


def join_to_csv_line(items: List[str]) -> str:
    return f"{','.join(items)}\n"


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
        limit=exported_asset.export_context.get("limit", 10_000),
    )
    logger.info("csv_exporter.read_from_clickhouse", number_of_results=len(result))

    if write_headers:
        temporary_file.write(join_to_csv_line(result[0].keys()).encode("utf-8"))

    for values in [row.values() for row in result]:
        line = [encode(v) for v in values]
        comma_separated_line = join_to_csv_line(line)
        temporary_file.write(comma_separated_line.encode("utf-8"))

    logger.info("csv_exporter.wrote_day_to_temp_file", day=day_filter.date_from)


def concat_results_in_object_storage(temporary_file: IO, exported_asset: ExportedAsset, root_bucket: str) -> str:
    object_path = f"/{root_bucket}/csvs/team-{exported_asset.team.id}/task-{exported_asset.id}/{UUIDT()}"
    temporary_file.seek(0)
    object_storage.write(object_path, gzip.compress(temporary_file.read()))
    logger.info("csv_exporter.wrote_to_object_storage", object_path=object_path)
    return object_path


def _export_to_csv(exported_asset: ExportedAsset, root_bucket: str) -> None:
    if exported_asset.export_context.get("file_export_type", None) == "list_events":
        filter = Filter(data=exported_asset.export_context.get("filter"))
        logger.info("csv_exporter.built_filter_from_context", filter=filter.to_dict())

        write_headers = True
        with tempfile.TemporaryFile() as temporary_file:
            for day_filter in filter.split_by_day():
                stage_results_to_object_storage(day_filter, exported_asset, temporary_file, write_headers)
                write_headers = False

            object_path = concat_results_in_object_storage(temporary_file, exported_asset, root_bucket)
            exported_asset.content_location = object_path
            exported_asset.save(update_fields=["content_location"])


def export_csv(exported_asset: ExportedAsset, root_bucket: str = settings.OBJECT_STORAGE_EXPORTS_FOLDER) -> None:
    timer = statsd.timer("csv_exporter").start()

    try:
        if exported_asset.export_format == "text/csv":
            _export_to_csv(exported_asset, root_bucket)
            statsd.incr("csv_exporter.succeeded", tags={"team_id": exported_asset.team.id})
        else:
            statsd.incr("csv_exporter.unknown_asset", tags={"team_id": exported_asset.team.id})
            raise NotImplementedError(f"Export to format {exported_asset.export_format} is not supported")
    except Exception as e:
        if exported_asset:
            team_id = str(exported_asset.team.id)
        else:
            team_id = "unknown"

        with push_scope() as scope:
            scope.set_tag("celery_task", "csv_export")
            capture_exception(e)

        logger.error("csv_exporter.failed", exception=e)
        statsd.incr("csv_exporter.failed", tags={"team_id": team_id})
        raise e
    finally:
        timer.stop()


def _export_to_csv_via_api(exported_asset: ExportedAsset, root_bucket: str) -> None:
    resource = exported_asset.export_context

    path: str = resource["path"]
    method: str = resource.get("method", "GET")
    body = resource.get("body", None)

    print(path, method, body)
    access_token = encode_jwt(
        {"id": exported_asset.created_by_id}, datetime.timedelta(minutes=15), PosthogJwtAudience.IMPERSONATED_USER
    )

    response = requests.request(
        method=method.lower(), url=absolute_uri(path), data=body, headers={"Authorization": f"Bearer {access_token}"}
    )

    data = response.json()
    print(data)


def export_csv_via_api(
    exported_asset: ExportedAsset, root_bucket: str = settings.OBJECT_STORAGE_EXPORTS_FOLDER
) -> None:
    timer = statsd.timer("csv_exporter").start()

    try:
        if exported_asset.export_format == "text/csv":
            _export_to_csv_via_api(exported_asset, root_bucket)
            statsd.incr("csv_exporter.succeeded", tags={"team_id": exported_asset.team.id})
        else:
            statsd.incr("csv_exporter.unknown_asset", tags={"team_id": exported_asset.team.id})
            raise NotImplementedError(f"Export to format {exported_asset.export_format} is not supported")
    except Exception as e:
        if exported_asset:
            team_id = str(exported_asset.team.id)
        else:
            team_id = "unknown"

        with push_scope() as scope:
            scope.set_tag("celery_task", "csv_export")
            capture_exception(e)

        logger.error("csv_exporter.failed", exception=e)
        statsd.incr("csv_exporter.failed", tags={"team_id": team_id})
        raise e
    finally:
        timer.stop()
