import re
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from aioresponses import aioresponses

from posthog.schema import HogQLQueryModifiers

from posthog.clickhouse.workload import Workload
from posthog.models.event.new_events_schema import events_route_scope
from posthog.temporal.common.clickhouse import get_client

if TYPE_CHECKING:
    from pytest_django.fixtures import Settings


@pytest.mark.parametrize(
    "workload,reads_events_json,host,database,cluster",
    [
        (None, False, "offline", "main_db", "main_cluster"),
        (Workload.DEFAULT, False, "offline", "main_db", "main_cluster"),
        (Workload.OFFLINE, False, "offline", "main_db", "main_cluster"),
        (Workload.ONLINE, False, "online", "main_db", "main_cluster"),
        (Workload.ENDPOINTS, True, "endpoints", "main_db", "main_cluster"),
        (Workload.LOGS, True, "logs", "logs_db", "logs_cluster"),
        (Workload.METRICS, True, "metrics", "metrics_db", "metrics_cluster"),
        (Workload.DEFAULT, True, "events-offline", "main_db", "events_cluster"),
        (Workload.OFFLINE, True, "events-offline", "main_db", "events_cluster"),
        (Workload.ONLINE, True, "events-online", "main_db", "events_cluster"),
    ],
)
@pytest.mark.parametrize("secure", [False, True], ids=["http", "https"])
@pytest.mark.parametrize("explicit_url", [None, "https://override.example.com:9443/"], ids=["routed", "explicit"])
async def test_get_client_routes_workload_with_deployment_credentials(
    settings: "Settings",
    tmp_path: Path,
    workload: Workload | None,
    reads_events_json: bool,
    host: str,
    database: str,
    cluster: str,
    secure: bool,
    explicit_url: str | None,
) -> None:
    settings.CLICKHOUSE_DATABASE = "main_db"
    settings.CLICKHOUSE_CLUSTER = "main_cluster"
    settings.CLICKHOUSE_EVENTS_CLUSTER = "events_cluster"
    settings.CLICKHOUSE_SECURE = not secure if workload in (Workload.LOGS, Workload.METRICS) else secure
    protocol, port = ("https", 8443) if secure else ("http", 8123)
    settings.CLICKHOUSE_HTTP_URL = f"{protocol}://online.example.com:{port}/"
    settings.CLICKHOUSE_OFFLINE_HTTP_URL = f"{protocol}://offline.example.com:{port}/"
    settings.CLICKHOUSE_EVENTS_ONLINE_HOST = "events-online.example.com"
    settings.CLICKHOUSE_EVENTS_OFFLINE_HOST = "events-offline.example.com"
    settings.CLICKHOUSE_EVENTS_ONLINE_HTTP_URL = f"{protocol}://events-online.example.com:{port}/"
    settings.CLICKHOUSE_EVENTS_OFFLINE_HTTP_URL = f"{protocol}://events-offline.example.com:{port}/"
    settings.CLICKHOUSE_ENDPOINTS_HOST = "endpoints.example.com"
    settings.CLICKHOUSE_LOGS_CLUSTER_HOST = "logs.example.com"
    settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE = "logs_db"
    settings.CLICKHOUSE_LOGS_CLUSTER = "logs_cluster"
    settings.CLICKHOUSE_LOGS_CLUSTER_SECURE = secure
    settings.CLICKHOUSE_LOGS_CLUSTER_USER = "logs_user"
    settings.CLICKHOUSE_LOGS_CLUSTER_PASSWORD = "unused-logs-password"
    settings.CLICKHOUSE_METRICS_CLUSTER_HOST = "metrics.example.com"
    settings.CLICKHOUSE_METRICS_CLUSTER_DATABASE = "metrics_db"
    settings.CLICKHOUSE_METRICS_CLUSTER = "metrics_cluster"
    settings.CLICKHOUSE_METRICS_CLUSTER_SECURE = secure
    settings.CLICKHOUSE_METRICS_CLUSTER_USER = "metrics_user"
    settings.CLICKHOUSE_METRICS_CLUSTER_PASSWORD = "unused-metrics-password"
    settings.CLICKHOUSE_USER = "batch_export"
    settings.CLICKHOUSE_PASSWORD = "batch-export-password"
    settings.CLICKHOUSE_PASSWORD_FILE = None

    expected_url = explicit_url or f"{protocol}://{host}.example.com:{port}/"
    request_url = re.compile(r"^" + re.escape(expected_url) + r"\?")
    if explicit_url is not None and cluster == "events_cluster":
        cluster = "main_cluster"
    workload_kwargs = {"workload": workload} if workload is not None else {}

    with (
        events_route_scope(HogQLQueryModifiers(useNewEventsSchema=reads_events_json)),
        aioresponses() as responses,
    ):
        responses.get(request_url, body="1\n", repeat=True)
        async with get_client(team_id=1, clickhouse_url=explicit_url, **workload_kwargs) as client:
            assert client.cluster == cluster
            assert await client.read_query("SELECT 1") == b"1\n"
            request = next(iter(responses.requests.values()))[-1]
            assert request.kwargs["params"]["database"] == database
            assert request.kwargs["headers"]["X-ClickHouse-User"] == "batch_export"
            assert request.kwargs["headers"]["X-ClickHouse-Key"] == "batch-export-password"
            assert "workload" not in request.kwargs["params"]

    token = tmp_path / "token"
    token.write_text("batch-export-token-0")
    settings.CLICKHOUSE_PASSWORD_FILE = str(token)
    with (
        events_route_scope(HogQLQueryModifiers(useNewEventsSchema=reads_events_json)),
        aioresponses() as responses,
    ):
        responses.get(request_url, body="1\n", repeat=True)
        async with get_client(team_id=1, clickhouse_url=explicit_url, **workload_kwargs) as client:
            assert await client.read_query("SELECT 1") == b"1\n"
            request = next(iter(responses.requests.values()))[-1]
            assert request.kwargs["headers"]["X-ClickHouse-Key"] == "batch-export-token-0"

            token.write_text("batch-export-token-1")
            assert await client.read_query("SELECT 1") == b"1\n"
            request = next(iter(responses.requests.values()))[-1]
            assert request.kwargs["headers"]["X-ClickHouse-Key"] == "batch-export-token-1"
