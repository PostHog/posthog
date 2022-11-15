import json
import time
from datetime import timedelta
from typing import Any

import requests
import structlog
from rest_framework.exceptions import NotFound, PermissionDenied
from sentry_sdk import capture_exception
from statshog.defaults.django import statsd

from posthog.internal_metrics import incr, timing
from posthog.jwt import PosthogJwtAudience, encode_jwt
from posthog.logging.timing import timed
from posthog.models.exported_asset import ExportedAsset, save_content
from posthog.utils import absolute_uri

logger = structlog.get_logger(__name__)


def make_api_call(access_token: str, body: Any, method: str, path: str) -> requests.models.Response:
    request_url: str = absolute_uri(path)
    try:
        response = requests.request(
            method=method.lower(), url=request_url, json=body, headers={"Authorization": f"Bearer {access_token}"}
        )
        return response
    except Exception as ex:
        logger.error(
            "json_exporter.error_making_api_call",
            exc=ex,
            exc_info=True,
            path=path,
            request_url=request_url,
        )

        raise ex


def _export_to_json(exported_asset: ExportedAsset) -> None:
    """
    Exporting a DashboardTemplate means:
    1. Loading the template from the provided API path
    2. Serialise it to JSON
    3. ???
    4. Profit
    """

    _start = time.time()
    export_context = exported_asset.export_context

    path: str = export_context["path"]

    method: str = export_context.get("method", "GET")
    body = export_context.get("body", None)

    access_token = encode_jwt(
        {"id": exported_asset.created_by_id}, timedelta(minutes=15), PosthogJwtAudience.IMPERSONATED_USER
    )

    response = make_api_call(access_token, body, method, path)

    # noinspection PyBroadException
    try:
        response_json = response.json()
    except Exception:
        response_json = "no response json to parse"

    if response.status_code != 200:
        if response.status_code == 404:
            raise NotFound(f"export API call failed with status_code: {response.status_code}. {response_json}")
        elif response.status_code == 403:
            raise PermissionDenied(f"export API call failed with status_code: {response.status_code}. {response_json}")
        else:
            raise Exception(f"export API call failed with status_code: {response.status_code}. {response_json}")

    save_content(exported_asset, json.dumps(response_json).encode("utf-8"))
    timing("exporter_task_success", time.time() - _start)


@timed("json_exporter")
def export_json(exported_asset: ExportedAsset) -> None:
    try:
        if exported_asset.export_format == "application/json":
            _export_to_json(exported_asset)
            statsd.incr("json_exporter.succeeded", tags={"team_id": exported_asset.team.id})
        else:
            raise NotImplementedError(f"Export to format {exported_asset.export_format} is not supported JSON")
    except Exception as e:
        if exported_asset:
            team_id = str(exported_asset.team.id)
        else:
            team_id = "unknown"

        capture_exception(e)

        logger.error("json_exporter.failed", exception=e, exc_info=True)
        incr("exporter_task_failure", tags={"team_id": team_id})
        raise e
