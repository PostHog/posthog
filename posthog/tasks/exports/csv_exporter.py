import io
import datetime
from collections.abc import Generator
from typing import Any, Optional
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse

from django.http import QueryDict

import requests
import structlog
from openpyxl import Workbook
from pydantic import BaseModel
from requests.exceptions import HTTPError

from posthog.api.services.query import process_query_dict
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.jwt import PosthogJwtAudience, encode_jwt
from posthog.models.exported_asset import ExportedAsset, save_content
from posthog.utils import absolute_uri

from ...exceptions import QuerySizeExceeded
from ...hogql.constants import CSV_EXPORT_BREAKDOWN_LIMIT_INITIAL, CSV_EXPORT_BREAKDOWN_LIMIT_LOW, CSV_EXPORT_LIMIT
from ...hogql.query import LimitContext
from ...hogql_queries.insights.trends.breakdown import (
    BREAKDOWN_NULL_DISPLAY,
    BREAKDOWN_NULL_STRING_LABEL,
    BREAKDOWN_OTHER_DISPLAY,
    BREAKDOWN_OTHER_STRING_LABEL,
)
from ..exporter import EXPORT_ASSET_UNKNOWN_COUNTER, EXPORT_FAILED_COUNTER, EXPORT_SUCCEEDED_COUNTER, EXPORT_TIMER
from .ordered_csv_renderer import OrderedCsvRenderer

logger = structlog.get_logger(__name__)

RESULT_LIMIT_KEYS = ("distinct_ids",)
RESULT_LIMIT_LENGTH = 10


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


def add_query_params(url: str, params: dict[str, str]) -> str:
    """
    Uses parse_qsl because parse_qs turns all values into lists but doesn't unbox them when re-encoded
    """
    parsed = urlparse(url)
    query_params = parse_qsl(parsed.query, keep_blank_values=True)

    update_params: list[tuple[str, Any]] = []
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


def _convert_response_to_csv_data(data: Any, breakdown_filter: Optional[dict] = None) -> Generator[Any, None, None]:
    if isinstance(data.get("results"), list):
        results = data.get("results")
        if len(results) > 0 and (isinstance(results[0], list) or isinstance(results[0], tuple)) and data.get("types"):
            # e.g. {'columns': ['count()'], 'hasMore': False, 'results': [[1775]], 'types': ['UInt64']}
            # or {'columns': ['count()', 'event'], 'hasMore': False, 'results': [[551, '$feature_flag_called'], [265, '$autocapture']], 'types': ['UInt64', 'String']}
            for row in results:
                row_dict = {}
                for idx, x in enumerate(row):
                    if isinstance(x, dict):
                        for key in filter(
                            lambda y: y in RESULT_LIMIT_KEYS and len(x[y]) > RESULT_LIMIT_LENGTH, x.keys()
                        ):
                            total = len(x[key])
                            x[key] = x[key][:RESULT_LIMIT_LENGTH]
                            row_dict[f"{key}.total"] = f"Note: {total} {key} in total"

                    if not data.get("columns"):
                        row_dict[f"column_{idx}"] = x
                    else:
                        row_dict[data["columns"][idx]] = x
                yield row_dict
            return

    if isinstance(data.get("results"), list) or isinstance(data.get("results"), dict):
        results = data.get("results")
    elif isinstance(data.get("result"), list) or isinstance(data.get("result"), dict):
        results = data.get("result")
    else:
        return None

    if isinstance(results, list):
        first_result = next(iter(results), None)

        if not first_result:
            return
        elif len(results) == 1 and isinstance(first_result, dict) and set(first_result.keys()) == {"people", "count"}:
            # persons modal like
            yield from results[0].get("people")
            return
        elif isinstance(first_result, list) or first_result.get("action_id"):
            multiple_items = results if isinstance(first_result, list) else [results]
            # FUNNELS LIKE
            for items in multiple_items:
                yield from (
                    {
                        "name": x.get("custom_name") or x.get("action_id", ""),
                        "breakdown_value": "::".join(x.get("breakdown_value", [])),
                        "action_id": x.get("action_id", ""),
                        "count": x.get("count", ""),
                        "median_conversion_time (seconds)": x.get("median_conversion_time", ""),
                        "average_conversion_time (seconds)": x.get("average_conversion_time", ""),
                    }
                    for x in items
                )
            return
        elif first_result.get("appearances") and first_result.get("person"):
            # RETENTION PERSONS LIKE
            period = data["filters"]["period"] or "Day"
            for item in results:
                line = {"person": item["person"]["name"]}
                for index, data in enumerate(item["appearances"]):
                    line[f"{period} {index}"] = data

                yield line
            return
        elif first_result.get("values") and first_result.get("label"):
            # RETENTION LIKE
            for item in results:
                if item.get("date"):
                    # Dated means we create a grid
                    line = {
                        "cohort": item["date"],
                        "cohort size": item["values"][0]["count"],
                    }
                    for data in item["values"]:
                        line[data["label"]] = data["count"]
                else:
                    # Otherwise we just specify "Period" for titles
                    line = {
                        "cohort": item["label"],
                        "cohort size": item["values"][0]["count"],
                    }
                    for index, data in enumerate(item["values"]):
                        line[f"Period {index}"] = data["count"]

                yield line
            return
        elif isinstance(first_result.get("data"), list) or (
            first_result.get("data") is None and "aggregated_value" in first_result
        ):
            is_comparison = first_result.get("compare_label")

            # take date labels from current results, when comparing against previous
            # as previous results will be indexed with offset
            date_labels_item = next((x for x in results if x.get("compare_label") == "current"), None)

            # TRENDS LIKE
            for index, item in enumerate(results):
                label = item.get("label", f"Series #{index + 1}")
                compare_label = item.get("compare_label", "")
                series_name = f"{label} - {compare_label}" if compare_label else label

                line = {"series": series_name}

                label_item = date_labels_item if is_comparison else item
                action = item.get("action")

                if isinstance(action, dict) and action.get("custom_name"):
                    line["custom name"] = action.get("custom_name")

                if "breakdown_value" in item:
                    breakdown_value = item.get("breakdown_value")
                    breakdown_values = breakdown_value if isinstance(breakdown_value, list) else [breakdown_value]

                    # Get breakdown property names from filter
                    breakdowns = breakdown_filter.get("breakdowns", []) if breakdown_filter else []
                    # For single breakdown, check legacy "breakdown" field
                    if not breakdowns and breakdown_filter and "breakdown" in breakdown_filter:
                        breakdowns = [{"property": breakdown_filter.get("breakdown")}]

                    for idx, val in enumerate(breakdown_values):
                        # Get the property name from the breakdown filter
                        prop_name = breakdowns[idx].get("property") if idx < len(breakdowns) else None
                        if not prop_name:
                            continue
                        # Format special breakdown values for display
                        formatted_val = str(val) if val is not None else ""
                        if formatted_val == BREAKDOWN_OTHER_STRING_LABEL:
                            formatted_val = BREAKDOWN_OTHER_DISPLAY
                        elif formatted_val == BREAKDOWN_NULL_STRING_LABEL:
                            formatted_val = BREAKDOWN_NULL_DISPLAY
                        line[prop_name] = formatted_val

                if item.get("aggregated_value") is not None:
                    line["Total Sum"] = item.get("aggregated_value")
                elif item.get("data"):
                    for index, data in enumerate(item["data"]):
                        line[label_item["labels"][index]] = data

                yield line

            return
    elif results and isinstance(results, dict):
        if "bins" in results:
            for key, value in results["bins"]:
                yield {"bin": key, "value": value}
            return

    # Pagination object
    yield from results
    return


class UnexpectedEmptyJsonResponse(Exception):
    pass


def get_from_insights_api(exported_asset: ExportedAsset, limit: int, resource: dict) -> Generator[Any, None, None]:
    path: str = resource["path"]
    method: str = resource.get("method", "GET")
    body = resource.get("body", None)
    next_url = None
    access_token = encode_jwt(
        {"id": exported_asset.created_by_id},
        datetime.timedelta(minutes=15),
        PosthogJwtAudience.IMPERSONATED_USER,
    )
    total = 0
    while total < CSV_EXPORT_LIMIT:
        try:
            response = make_api_call(access_token, body, limit, method, next_url, path)
        except HTTPError as e:
            if "Query size exceeded" not in e.response.text:
                raise

            if limit <= CSV_EXPORT_BREAKDOWN_LIMIT_LOW:
                break  # Already tried with the lowest limit, so return what we have

            # If error message contains "Query size exceeded", we try again with a lower limit
            limit = int(limit / 2)
            logger.warning(
                "csv_exporter.query_size_exceeded",
                exc=e,
                exc_info=True,
                response_text=e.response.text,
                limit=limit,
            )
            continue

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

        csv_rows = list(_convert_response_to_csv_data(data))
        total += len(csv_rows)
        yield from csv_rows

        if not data.get("next") or not csv_rows:
            break

        next_url = data.get("next")


def get_from_hogql_query(exported_asset: ExportedAsset, limit: int, resource: dict) -> Generator[Any, None, None]:
    query = resource.get("source")
    assert query is not None

    while True:
        try:
            query_response = process_query_dict(
                team=exported_asset.team,
                query_json=query,
                limit_context=LimitContext.EXPORT,
                execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
            )
        except QuerySizeExceeded:
            if "breakdownFilter" not in query or limit <= CSV_EXPORT_BREAKDOWN_LIMIT_LOW:
                raise

            # HACKY: Adjust the breakdown_limit in the query
            limit = int(limit / 2)
            query["breakdownFilter"]["breakdown_limit"] = limit
            continue

        if isinstance(query_response, BaseModel):
            query_response = query_response.model_dump(by_alias=True)

        breakdown_filter = query.get("breakdownFilter") if query else None
        yield from _convert_response_to_csv_data(query_response, breakdown_filter=breakdown_filter)
        return


def _export_to_dict(exported_asset: ExportedAsset, limit: int) -> Any:
    resource = exported_asset.export_context

    columns: list[str] = resource.get("columns", [])
    returned_rows: Generator[Any, None, None]

    if resource.get("source"):
        returned_rows = get_from_hogql_query(exported_asset, limit, resource)
    else:
        returned_rows = get_from_insights_api(exported_asset, limit, resource)

    all_csv_rows = list(returned_rows)
    renderer = OrderedCsvRenderer()
    render_context = {}
    if columns:
        render_context["header"] = columns

    if len(all_csv_rows):
        # NOTE: This is not ideal as some rows _could_ have different keys
        # Ideally we would extend the csvrenderer to supported keeping the order in place
        is_any_col_list_or_dict = [x for x in all_csv_rows[0].values() if isinstance(x, dict) or isinstance(x, list)]
        if not is_any_col_list_or_dict:
            # If values are serialised then keep the order of the keys, else allow it to be unordered
            renderer.header = all_csv_rows[0].keys()
    else:
        # If we have no rows, that means we couldn't convert anything, so put something to avoid confusion
        all_csv_rows = [{"error": "No data available or unable to format for export."}]

    return renderer, all_csv_rows, render_context


def _export_to_csv(exported_asset: ExportedAsset, limit: int) -> None:
    renderer, all_csv_rows, render_context = _export_to_dict(exported_asset, limit)

    rendered_csv_content = renderer.render(all_csv_rows, renderer_context=render_context)
    save_content(exported_asset, rendered_csv_content)


def _export_to_excel(exported_asset: ExportedAsset, limit: int) -> None:
    output = io.BytesIO()

    workbook = Workbook()
    worksheet = workbook.active

    renderer, all_csv_rows, render_context = _export_to_dict(exported_asset, limit)

    for row_num, row_data in enumerate(renderer.tablize(all_csv_rows, header=render_context.get("header"))):
        for col_num, value in enumerate(row_data):
            if value is not None and not isinstance(value, str | int | float | bool):
                value = str(value)
            worksheet.cell(row=row_num + 1, column=col_num + 1, value=value)

    workbook.save(output)
    output.seek(0)
    save_content(exported_asset, output.getvalue())


def get_limit_param_key(path: str) -> str:
    query = QueryDict(path)
    breakdown = query.get("breakdown", None)
    return "breakdown_limit" if breakdown is not None else "limit"


def make_api_call(
    access_token: str,
    body: Any,
    limit: int,
    method: str,
    next_url: Optional[str],
    path: str,
) -> requests.models.Response:
    request_url: str = absolute_uri(next_url or path)
    url = add_query_params(
        request_url,
        {get_limit_param_key(request_url): str(limit), "is_csv_export": "1"},
    )
    response = requests.request(
        method=method.lower(),
        url=url,
        json=body,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=60,
    )
    response.raise_for_status()
    return response


def export_tabular(exported_asset: ExportedAsset, limit: Optional[int] = None) -> None:
    if not limit:
        limit = CSV_EXPORT_BREAKDOWN_LIMIT_INITIAL

    try:
        if exported_asset.export_format == ExportedAsset.ExportFormat.CSV:
            with EXPORT_TIMER.labels(type="csv").time():
                _export_to_csv(exported_asset, limit)
            EXPORT_SUCCEEDED_COUNTER.labels(type="csv").inc()
        elif exported_asset.export_format == ExportedAsset.ExportFormat.XLSX:
            with EXPORT_TIMER.labels(type="xlsx").time():
                _export_to_excel(exported_asset, limit)
            EXPORT_SUCCEEDED_COUNTER.labels(type="xlsx").inc()
        else:
            EXPORT_ASSET_UNKNOWN_COUNTER.labels(type="csv").inc()
            raise NotImplementedError(f"Export to format {exported_asset.export_format} is not supported")
    except Exception as e:
        if exported_asset:
            team_id = str(exported_asset.team.id)
        else:
            team_id = "unknown"

        capture_exception(e, additional_properties={"celery_task": "csv_export", "team_id": team_id})

        logger.error("csv_exporter.failed", exception=e, exc_info=True)
        EXPORT_FAILED_COUNTER.labels(type="csv").inc()
        raise
