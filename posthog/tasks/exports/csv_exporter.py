import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import requests
import structlog
from django.conf import settings
from rest_framework_csv import renderers as csvrenderers
from sentry_sdk import capture_exception, push_scope
from statshog.defaults.django import statsd

from posthog.jwt import PosthogJwtAudience, encode_jwt
from posthog.logging.timing import timed
from posthog.models.exported_asset import ExportedAsset
from posthog.models.utils import UUIDT
from posthog.storage import object_storage
from posthog.storage.object_storage import ObjectStorageError
from posthog.utils import absolute_uri

logger = structlog.get_logger(__name__)


# SUPPORTED CSV TYPES

# - Insights - Trends (Series Linear, Series Cumulative, Totals)
# Funnels - steps as data
# Retention
# Paths
# Lifecycle
# Via dashboard e.g. all of the above

# - People
# Cohorts
# Retention
# Funnel

# - Events
# Filtered

# HOW DOES THIS WORK
# 1. We receive an export task with a given resource uri (identical to the API)
# 2. We call the actual API to load the data with the given params so that we receive a paginateable response
# 3. We save the response to a chunk in object storage and then load the `next` page of results
# 4. Repeat until exhausted or limit reached
# 5. We save the final blob output and update the ExportedAsset


def _modifiy_query(url: str, params: Dict[str, List[str]]) -> str:
    parsed = urlparse(url)
    query_params = parse_qs(parsed.query)
    query_params.update(params)
    parsed._replace(query=urlencode(query_params))
    return urlunparse(parsed)


def _convert_response_to_csv_data(data: Any) -> List[Any]:
    if isinstance(data.get("results"), list):
        # Pagination object
        return data.get("results")
    elif data.get("result") and isinstance(data.get("result"), list):
        items = data["result"]
        first_result = items[0]

        if first_result.get("appearances") and first_result.get("person"):
            # RETENTION PERSONS LIKE
            csv_rows = []
            for item in items:
                line = {
                    "person": item["person"].get("properties").get("email")
                    or item["person"].get("properties").get("id")
                }
                for index, data in enumerate(item["appearances"]):
                    line[f"Day {index}"] = data

                csv_rows.append(line)
            return csv_rows
        elif first_result.get("values") and first_result.get("label"):
            csv_rows = []
            # RETENTION LIKE
            for item in items:
                line = {"cohort": item["date"], "cohort size": item["values"][0]["count"]}
                for index, data in enumerate(item["values"]):
                    line[items[index]["label"]] = data["count"]

                csv_rows.append(line)
            return csv_rows
        elif isinstance(first_result.get("data"), list):
            csv_rows = []
            # TRENDS LIKE
            for item in items:
                line = {"series": item["label"]}
                if item.get("action").get("custom_name"):
                    line["custom name"] = item.get("action").get("custom_name")
                if item.get("aggregated_value"):
                    line["total count"] = item.get("aggregated_value")
                else:
                    for index, data in enumerate(item["data"]):
                        line[item["labels"][index]] = data

                csv_rows.append(line)

            return csv_rows
        elif first_result.get("action_id"):
            # FUNNELS LIKE
            csv_rows = [
                {
                    "name": x["custom_name"] or x["action_id"],
                    "action_id": x["action_id"],
                    "count": x["count"],
                    "median_conversion_time (seconds)": x["median_conversion_time"],
                    "average_conversion_time (seconds)": x["average_conversion_time"],
                }
                for x in items
            ]

            return csv_rows
        else:
            return items

    return []


def _export_to_csv(exported_asset: ExportedAsset, limit: int = 1000, max_limit: int = 10_000,) -> None:
    resource = exported_asset.export_context

    path: str = resource["path"]

    method: str = resource.get("method", "GET")
    body = resource.get("body", None)

    access_token = encode_jwt(
        {"id": exported_asset.created_by_id}, datetime.timedelta(minutes=15), PosthogJwtAudience.IMPERSONATED_USER
    )

    next_url = None
    all_csv_rows: List[Any] = []

    while len(all_csv_rows) < max_limit:
        url = _modifiy_query(next_url or absolute_uri(path), {"limit": [str(limit)]})

        response = requests.request(
            method=method.lower(), url=url, json=body, headers={"Authorization": f"Bearer {access_token}"},
        )

        # Figure out how to handle funnel polling....

        data = response.json()

        csv_rows = _convert_response_to_csv_data(data)

        all_csv_rows = all_csv_rows + csv_rows

        if not data.get("next") or not csv_rows:
            break

        next_url = data.get("next")

    renderer = csvrenderers.CSVRenderer()

    # NOTE: This is not ideal as some rows _could_ have different keys
    # Ideally we would extend the csvrenderer to supported keeping the order in place
    if len(all_csv_rows):
        if not [x for x in all_csv_rows[0].values() if isinstance(x, dict) or isinstance(x, list)]:
            # If values are serialised then keep the order of the keys, else allow it to be unordered
            renderer.header = all_csv_rows[0].keys()

    rendered_csv_content = renderer.render(all_csv_rows)
    try:
        if settings.OBJECT_STORAGE_ENABLED:
            _write_to_object_storage(exported_asset, rendered_csv_content)
        else:
            _write_to_exported_asset(exported_asset, rendered_csv_content)
    except ObjectStorageError as ose:
        logger.error("csv_exporter.object-storage-error", exception=ose, exc_info=True)
        _write_to_exported_asset(exported_asset, rendered_csv_content)


def _write_to_exported_asset(exported_asset, rendered_csv_content):
    exported_asset.content = rendered_csv_content
    exported_asset.save(update_fields=["content"])


def _write_to_object_storage(exported_asset, rendered_csv_content):
    object_path = f"/{settings.OBJECT_STORAGE_EXPORTS_FOLDER}/csvs/team-{exported_asset.team.id}/task-{exported_asset.id}/{UUIDT()}"
    object_storage.write(object_path, rendered_csv_content)
    exported_asset.content_location = object_path
    exported_asset.save(update_fields=["content_location"])


@timed("csv_exporter")
def export_csv(exported_asset: ExportedAsset, limit: Optional[int] = None, max_limit: int = 10_000,) -> None:
    if not limit:
        limit = 1000

    try:
        if exported_asset.export_format == "text/csv":
            _export_to_csv(exported_asset, limit, max_limit)
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
