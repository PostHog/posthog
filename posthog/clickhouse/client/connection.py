import json
import logging
import os
from contextlib import contextmanager
from enum import Enum
from functools import cache
from collections.abc import Mapping

from cachetools import cached, TTLCache
from contextlib import suppress
from clickhouse_connect import get_client
from clickhouse_connect.driver import Client as HttpClient, httputil
from clickhouse_driver import Client as SyncClient
from clickhouse_pool import ChPool
from django.conf import settings
import posthoganalytics


from posthog.settings import data_stores
from posthog.utils import patchable, get_instance_region


class Workload(Enum):
    # Default workload
    DEFAULT = "DEFAULT"
    # Analytics queries, other 'lively' queries
    ONLINE = "ONLINE"
    # Historical exports, other long-running processes where latency is less critical
    OFFLINE = "OFFLINE"
    # Logs queries
    LOGS = "LOGS"


class NodeRole(Enum):
    ALL = "ALL"
    COORDINATOR = "COORDINATOR"
    DATA = "DATA"


_default_workload = Workload.ONLINE


class ClickHouseUser(Enum):
    # Default, not annotated queries goes here.
    DEFAULT = "default"
    # All /api/ requests called programmatically
    API = "api"
    # All /api/ requests coming from our app
    APP = "app"
    BATCH_EXPORT = "batch_export"
    COHORTS = "cohorts"
    CACHE_WARMUP = "cache_warmup"

    # Dev Operations - do not normally use
    OPS = "ops"
    # Only for migrations - do not normally use
    MIGRATIONS = "migrations"


__user_dict: Mapping[ClickHouseUser, tuple[str, str]] | None = None


def init_clickhouse_users() -> Mapping[ClickHouseUser, tuple[str, str]]:
    user_dict = {
        ClickHouseUser.DEFAULT: (data_stores.CLICKHOUSE_USER, data_stores.CLICKHOUSE_PASSWORD),
    }
    for u in ClickHouseUser:
        user = os.getenv(f"CLICKHOUSE_{u.name.upper()}_USER")
        password = os.getenv(f"CLICKHOUSE_{u.name.upper()}_PASSWORD")
        if user and password:
            user_dict[u] = (user, password)
        elif bool(user) != bool(password):
            logging.warning(f"only one of clickhouse user/password provided, check your config")
    user_names = ",".join([x.name for x in user_dict.keys()])
    logging.warning(f"initialized clickhouse users: {user_names}")
    return user_dict


def get_clickhouse_creds(user: ClickHouseUser) -> tuple[str, str]:
    global __user_dict
    if not __user_dict:
        __user_dict = init_clickhouse_users()
    return __user_dict[user] if user in __user_dict else __user_dict[ClickHouseUser.DEFAULT]


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
        "host": settings.CLICKHOUSE_HOST,
        "database": settings.CLICKHOUSE_DATABASE,
        "secure": settings.CLICKHOUSE_SECURE,
        "user": settings.CLICKHOUSE_USER,  # kwargs have user not username
        "password": settings.CLICKHOUSE_PASSWORD,
        "settings": {"mutations_sync": "1"} if settings.TEST else {},
        # Without this, OPTIMIZE table and other queries will regularly run into timeouts
        "send_receive_timeout": 30 if settings.TEST else 999_999_999,
        "autogenerate_session_id": True,
        # beware, this makes each query to run in a separate session - no temporary tables will work
        "pool_mgr": _clickhouse_http_pool_mgr,
        **overrides,
    }
    yield ProxyClient(get_client(**kwargs))


@cached(cache=TTLCache(maxsize=1, ttl=900))
def get_teams_enabled_for_clickhouse_http() -> set[int]:
    if instance_region := get_instance_region():
        with suppress(Exception):
            cfg = json.loads(posthoganalytics.get_remote_config_payload("team-enabled-for-clickhouse-http"))
            return set(cfg[instance_region]) or set[int]()
    return set[int]()


def get_kwargs_for_client(
    workload: Workload = Workload.DEFAULT,
    team_id=None,
    readonly=False,
    ch_user: ClickHouseUser = ClickHouseUser.DEFAULT,
):
    if workload == Workload.LOGS:
        return {
            "host": settings.CLICKHOUSE_LOGS_CLUSTER_HOST,
            "database": settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE,
            "user": settings.CLICKHOUSE_LOGS_CLUSTER_USER,
            "password": settings.CLICKHOUSE_LOGS_CLUSTER_PASSWORD,
            "secure": settings.CLICKHOUSE_LOGS_CLUSTER_SECURE,
        }

    (user, password) = get_clickhouse_creds(ch_user)
    base_kwargs = {"user": user, "password": password}

    if team_id is not None and str(team_id) in settings.CLICKHOUSE_PER_TEAM_SETTINGS:
        user_settings = settings.CLICKHOUSE_PER_TEAM_SETTINGS[str(team_id)]
        return {**base_kwargs, **user_settings}

    # Note that `readonly` does nothing if the relevant vars are not set!
    if readonly and settings.READONLY_CLICKHOUSE_USER is not None and settings.READONLY_CLICKHOUSE_PASSWORD:
        return {
            "user": settings.READONLY_CLICKHOUSE_USER,
            "password": settings.READONLY_CLICKHOUSE_PASSWORD,
        }

    if (
        workload == Workload.OFFLINE or workload == Workload.DEFAULT and _default_workload == Workload.OFFLINE
    ) and settings.CLICKHOUSE_OFFLINE_CLUSTER_HOST is not None:
        return {**base_kwargs, "host": settings.CLICKHOUSE_OFFLINE_CLUSTER_HOST, "verify": False}

    return base_kwargs


@patchable
def get_client_from_pool(
    workload: Workload = Workload.DEFAULT,
    team_id=None,
    readonly=False,
    ch_user: ClickHouseUser = ClickHouseUser.DEFAULT,
):
    """
    Returns the client for a given workload.

    The connection pool for HTTP is managed by a library.
    """

    if settings.CLICKHOUSE_USE_HTTP or team_id in get_teams_enabled_for_clickhouse_http():
        kwargs = get_kwargs_for_client(workload=workload, team_id=team_id, readonly=readonly, ch_user=ch_user)
        return get_http_client(**kwargs)

    return get_pool(workload=workload, team_id=team_id, readonly=readonly, ch_user=ch_user).get_client()


def get_pool(
    workload: Workload = Workload.DEFAULT,
    team_id=None,
    readonly=False,
    ch_user: ClickHouseUser = ClickHouseUser.DEFAULT,
):
    """
    Returns the right connection pool given a workload.

    Note that the same pool should be returned every call.
    """
    kwargs = get_kwargs_for_client(workload=workload, team_id=team_id, readonly=readonly, ch_user=ch_user)
    return make_ch_pool(**kwargs)


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


def get_default_clickhouse_workload_type():
    global _default_workload
    return _default_workload


@contextmanager
def set_default_clickhouse_workload_type(workload: Workload):
    global _default_workload

    _default_workload = workload


ch_pool = get_pool(workload=Workload.ONLINE)
