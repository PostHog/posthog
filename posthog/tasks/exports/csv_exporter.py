import csv
import datetime
from typing import Any, List, Optional

import requests
import structlog
from rest_framework_csv import renderers as csvrenderers
from sentry_sdk import capture_exception, push_scope
from statshog.defaults.django import statsd

from posthog import settings
from posthog.jwt import PosthogJwtAudience, encode_jwt
from posthog.models.exported_asset import ExportedAsset
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


def _export_to_csv(
    exported_asset: ExportedAsset, root_bucket: str, limit: int = 1000, max_limit: int = 10_000,
) -> None:
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
        url = next_url or absolute_uri(path)
        url += f"{'&' if '?' in url else '?'}limit={limit}"  # todo what if limit is already in URL

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
    renderer.writer_opts = {
        "quoting": csv.QUOTE_ALL,
    }

    exported_asset.content = renderer.render(all_csv_rows)
    exported_asset.save(update_fields=["content"])


def export_csv(
    exported_asset: ExportedAsset,
    root_bucket: str = settings.OBJECT_STORAGE_EXPORTS_FOLDER,
    limit: Optional[int] = None,
    max_limit: int = 10_000,
) -> None:
    timer = statsd.timer("csv_exporter").start()

    if not limit:
        limit = 1000

    try:
        if exported_asset.export_format == "text/csv":
            _export_to_csv(exported_asset, root_bucket, limit, max_limit)
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
