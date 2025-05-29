from contextlib import contextmanager
from enum import Enum
from functools import cache
from collections.abc import Mapping

from clickhouse_connect import get_client
from clickhouse_connect.driver import Client as HttpClient, httputil
from clickhouse_driver import Client as SyncClient
from clickhouse_pool import ChPool
from django.conf import settings

from posthog.utils import patchable


class Workload(Enum):
    # Default workload
    DEFAULT = "DEFAULT"
    # Analytics queries, other 'lively' queries
    ONLINE = "ONLINE"
    # Historical exports, other long-running processes where latency is less critical
    OFFLINE = "OFFLINE"


class NodeRole(Enum):
    ALL = "ALL"
    COORDINATOR = "COORDINATOR"
    DATA = "DATA"


_default_workload = Workload.ONLINE


class ProxyClient:
    def __init__(self, client: HttpClient):
        self._client = client

    def execute(
        self,
        query,
        params=None,
        with_column_types=False,
        external_tables=None,
        query_id=None,
        settings=None,
        types_check=False,
        columnar=False,
    ):
        if query_id:
            settings["query_id"] = query_id
        result = self._client.query(query=query, parameters=params, settings=settings, column_oriented=columnar)

        # we must play with result summary here
        written_rows = int(result.summary.get("written_rows", 0))
        if written_rows > 0:
            return written_rows
        if with_column_types:
            column_types_driver_format = [(a, b.name) for (a, b) in zip(result.column_names, result.column_types)]
            return result.result_set, column_types_driver_format
        return result.result_set

    # Implement methods for session managment: https://peps.python.org/pep-0343/ so ProxyClient can be used in all places a clickhouse_driver.Client is.
    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


_clickhouse_http_pool_mgr = httputil.get_pool_manager(
    maxsize=settings.CLICKHOUSE_CONN_POOL_MAX,  # max number of open connection per pool
    block=True,  # makes the maxsize limit per pool, keeps connections
    num_pools=12,  # number of pools
    ca_cert=settings.CLICKHOUSE_CA,
    verify=settings.QUERYSERVICE_VERIFY,
)


@contextmanager
def get_http_client(**overrides):
    kwargs = {
        "host": settings.QUERYSERVICE_HOST,
        "database": settings.CLICKHOUSE_DATABASE,
        "secure": settings.QUERYSERVICE_SECURE,
        "username": settings.CLICKHOUSE_USER,
        "password": settings.CLICKHOUSE_PASSWORD,
        "settings": {"mutations_sync": "1"} if settings.TEST else {},
        # Without this, OPTIMIZE table and other queries will regularly run into timeouts
        "send_receive_timeout": 30 if settings.TEST else 999_999_999,
        "autogenerate_session_id": True,  # beware, this makes each query to run in a separate session - no temporary tables will work
        "pool_mgr": _clickhouse_http_pool_mgr,
        **overrides,
    }
    yield ProxyClient(get_client(**kwargs))


@patchable
def get_client_from_pool(workload: Workload = Workload.DEFAULT, team_id=None, readonly=False):
    """
    Returns the client for a given workload.

    The connection pool for HTTP is managed by a library.
    """
    if settings.CLICKHOUSE_USE_HTTP:
        if team_id is not None and str(team_id) in settings.CLICKHOUSE_PER_TEAM_SETTINGS:
            return get_http_client(**settings.CLICKHOUSE_PER_TEAM_SETTINGS[str(team_id)])

        # Note that `readonly` does nothing if the relevant vars are not set!
        if readonly and settings.READONLY_CLICKHOUSE_USER is not None and settings.READONLY_CLICKHOUSE_PASSWORD:
            return get_http_client(
                username=settings.READONLY_CLICKHOUSE_USER,
                password=settings.READONLY_CLICKHOUSE_PASSWORD,
            )

        if (
            workload == Workload.OFFLINE or workload == Workload.DEFAULT and _default_workload == Workload.OFFLINE
        ) and settings.CLICKHOUSE_OFFLINE_CLUSTER_HOST is not None:
            return get_http_client(host=settings.CLICKHOUSE_OFFLINE_CLUSTER_HOST, verify=False)

        return get_http_client()

    return get_pool(workload=workload, team_id=team_id, readonly=readonly).get_client()


def get_pool(workload: Workload = Workload.DEFAULT, team_id=None, readonly=False):
    """
    Returns the right connection pool given a workload.

    Note that the same pool should be returned every call.
    """
    if team_id is not None and str(team_id) in settings.CLICKHOUSE_PER_TEAM_SETTINGS:
        return make_ch_pool(**settings.CLICKHOUSE_PER_TEAM_SETTINGS[str(team_id)])

    # Note that `readonly` does nothing if the relevant vars are not set!
    if readonly and settings.READONLY_CLICKHOUSE_USER is not None and settings.READONLY_CLICKHOUSE_PASSWORD:
        return make_ch_pool(
            user=settings.READONLY_CLICKHOUSE_USER,
            password=settings.READONLY_CLICKHOUSE_PASSWORD,
        )

    if (
        workload == Workload.OFFLINE or workload == Workload.DEFAULT and _default_workload == Workload.OFFLINE
    ) and settings.CLICKHOUSE_OFFLINE_CLUSTER_HOST is not None:
        return make_ch_pool(host=settings.CLICKHOUSE_OFFLINE_CLUSTER_HOST, verify=False)

    return make_ch_pool()


def default_client(host=settings.CLICKHOUSE_HOST):
    """
    Return a bare bones client for use in places where we are only interested in general ClickHouse state
    DO NOT USE THIS FOR QUERYING DATA
    """
    return SyncClient(
        host=host,
        # We set "system" here as we don't necessarily have a "default" database,
        # which is what the clickhouse_driver would use by default. We are
        # assuming that this exists and we have permissions to access it. This
        # feels like a reasonably safe assumption as e.g. we already reference
        # `system.numbers` in multiple places within queries. We also assume
        # access to various other tables e.g. to handle async migrations.
        database="system",
        secure=settings.CLICKHOUSE_SECURE,
        user=settings.CLICKHOUSE_USER,
        password=settings.CLICKHOUSE_PASSWORD,
        ca_certs=settings.CLICKHOUSE_CA,
        verify=settings.CLICKHOUSE_VERIFY,
    )


def _make_ch_pool(*, client_settings: Mapping[str, str] | None = None, **overrides) -> ChPool:
    kwargs = {
        "host": settings.CLICKHOUSE_HOST,
        "database": settings.CLICKHOUSE_DATABASE,
        "secure": settings.CLICKHOUSE_SECURE,
        "user": settings.CLICKHOUSE_USER,
        "password": settings.CLICKHOUSE_PASSWORD,
        "ca_certs": settings.CLICKHOUSE_CA,
        "verify": settings.CLICKHOUSE_VERIFY,
        "connections_min": settings.CLICKHOUSE_CONN_POOL_MIN,
        "connections_max": settings.CLICKHOUSE_CONN_POOL_MAX,
        "settings": {
            **({"mutations_sync": "1"} if settings.TEST else {}),
            **(client_settings or {}),
        },
        # Without this, OPTIMIZE table and other queries will regularly run into timeouts
        "send_receive_timeout": 30 if settings.TEST else 999_999_999,
        **overrides,
    }

    return ChPool(**kwargs)


make_ch_pool = cache(_make_ch_pool)


@contextmanager
def set_default_clickhouse_workload_type(workload: Workload):
    global _default_workload

    _default_workload = workload


ch_pool = get_pool(workload=Workload.ONLINE)
