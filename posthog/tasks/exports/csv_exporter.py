import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse

import requests
import structlog
from sentry_sdk import capture_exception, push_scope
from statshog.defaults.django import statsd

from posthog.jwt import PosthogJwtAudience, encode_jwt
from posthog.logging.timing import timed
from posthog.models.exported_asset import ExportedAsset, save_content
from posthog.utils import absolute_uri

from .ordered_csv_renderer import OrderedCsvRenderer

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


def add_query_params(url: str, params: Dict[str, str]) -> str:
    """
    Uses parse_qsl because parse_qs turns all values into lists but doesn't unbox them when re-encoded
    """
    parsed = urlparse(url)
    query_params = parse_qsl(parsed.query, keep_blank_values=True)

    update_params: List[Tuple[str, Any]] = []
    for param, value in query_params:
        if param in params:
            update_params.append((param, params.pop(param)))
        else:
            update_params.append((param, value))

    for key, value in params.items():
        update_params.append((key, value))

    encodedQueryParams = urlencode(update_params, quote_via=quote)
    parsed = parsed._replace(query=encodedQueryParams)
    return urlunparse(parsed)


def _convert_response_to_csv_data(data: Any) -> List[Any]:
    if isinstance(data.get("results"), list):
        results = data.get("results")

        # query like
        if isinstance(results[0], list) and "types" in data:
            # e.g. {'columns': ['count()'], 'hasMore': False, 'results': [[1775]], 'types': ['UInt64']}
            # or {'columns': ['count()', 'event'], 'hasMore': False, 'results': [[551, '$feature_flag_called'], [265, '$autocapture']], 'types': ['UInt64', 'String']}
            csv_rows: List[Dict[str, Any]] = []
            for row in results:
                row_dict = {}
                for idx, x in enumerate(row):
                    row_dict[data["columns"][idx]] = x
                csv_rows.append(row_dict)
            return csv_rows

        # persons modal like
        if len(results) == 1 and set(results[0].keys()) == {"people", "count"}:
            return results[0].get("people")

        # Pagination object
        return results
    elif data.get("result") and isinstance(data.get("result"), list):
        items = data["result"]
        first_result = items[0]

        if isinstance(first_result, list) or first_result.get("action_id"):
            csv_rows = []
            multiple_items = items if isinstance(first_result, list) else [items]
            # FUNNELS LIKE

            for items in multiple_items:
                csv_rows.extend(
                    [
                        {
                            "name": x["custom_name"] or x["action_id"],
                            "breakdown_value": "::".join(x.get("breakdown_value", [])),
                            "action_id": x["action_id"],
                            "count": x["count"],
                            "median_conversion_time (seconds)": x["median_conversion_time"],
                            "average_conversion_time (seconds)": x["average_conversion_time"],
                        }
                        for x in items
                    ]
                )

            return csv_rows
        elif first_result.get("appearances") and first_result.get("person"):
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
                if item.get("date"):
                    # Dated means we create a grid
                    line = {"cohort": item["date"], "cohort size": item["values"][0]["count"]}
                    for index, data in enumerate(item["values"]):
                        line[items[index]["label"]] = data["count"]
                else:
                    # Otherwise we just specify "Period" for titles
                    line = {"cohort": item["label"], "cohort size": item["values"][0]["count"]}
                    for index, data in enumerate(item["values"]):
                        line[f"Period {index}"] = data["count"]

                csv_rows.append(line)
            return csv_rows
        elif isinstance(first_result.get("data"), list):
            csv_rows = []
            # TRENDS LIKE
            for item in items:
                line = {"series": item["label"]}
                if item.get("action", {}).get("custom_name"):
                    line["custom name"] = item.get("action").get("custom_name")
                if item.get("aggregated_value"):
                    line["total count"] = item.get("aggregated_value")
                else:
                    for index, data in enumerate(item["data"]):
                        line[item["labels"][index]] = data

                csv_rows.append(line)

            return csv_rows
        else:
            return items

    return []


class UnexpectedEmptyJsonResponse(Exception):
    pass


def _export_to_csv(exported_asset: ExportedAsset, limit: int = 1000, max_limit: int = 3_500) -> None:
    resource = exported_asset.export_context

    path: str = resource["path"]
    columns: List[str] = resource.get("columns", [])

    method: str = resource.get("method", "GET")
    body = resource.get("body", None)

    access_token = encode_jwt(
        {"id": exported_asset.created_by_id}, datetime.timedelta(minutes=15), PosthogJwtAudience.IMPERSONATED_USER
    )

    next_url = None
    all_csv_rows: List[Any] = []

    while len(all_csv_rows) < max_limit:
        response = make_api_call(access_token, body, limit, method, next_url, path)

        if response.status_code != 200:
            # noinspection PyBroadException
            try:
                response_json = response.json()
            except Exception:
                response_json = "no response json to parse"
            raise Exception(f"export API call failed with status_code: {response.status_code}. {response_json}")

        # Figure out how to handle funnel polling....
        data = response.json()

        if data is None:
            unexpected_empty_json_response = UnexpectedEmptyJsonResponse("JSON is None when calling API for data")
            logger.error(
                "csv_exporter.json_was_none",
                exc=unexpected_empty_json_response,
                exc_info=True,
                response_text=response.text,
            )

            raise unexpected_empty_json_response

        csv_rows = _convert_response_to_csv_data(data)

        all_csv_rows = all_csv_rows + csv_rows

        if not data.get("next") or not csv_rows:
            break

        next_url = data.get("next")

    renderer = OrderedCsvRenderer()

    # NOTE: This is not ideal as some rows _could_ have different keys
    # Ideally we would extend the csvrenderer to supported keeping the order in place
    if len(all_csv_rows):
        if not [x for x in all_csv_rows[0].values() if isinstance(x, dict) or isinstance(x, list)]:
            # If values are serialised then keep the order of the keys, else allow it to be unordered
            renderer.header = all_csv_rows[0].keys()

    render_context = {}
    if columns:
        render_context["header"] = columns

    rendered_csv_content = renderer.render(all_csv_rows, renderer_context=render_context)
    save_content(exported_asset, rendered_csv_content)


def make_api_call(
    access_token: str, body: Any, limit: int, method: str, next_url: Optional[str], path: str
) -> requests.models.Response:
    request_url: str = absolute_uri(next_url or path)
    try:
        url = add_query_params(request_url, {"limit": str(limit), "is_csv_export": "1"})
        response = requests.request(
            method=method.lower(), url=url, json=body, headers={"Authorization": f"Bearer {access_token}"}
        )
        return response
    except Exception as ex:
        logger.error(
            "csv_exporter.error_making_api_call",
            exc=ex,
            exc_info=True,
            next_url=next_url,
            path=path,
            request_url=request_url,
            limit=limit,
        )
        raise ex


@timed("csv_exporter")
def export_csv(exported_asset: ExportedAsset, limit: Optional[int] = None, max_limit: int = 3_500) -> None:
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

        logger.error("csv_exporter.failed", exception=e, exc_info=True)
        statsd.incr("csv_exporter.failed", tags={"team_id": team_id})
        raise e
