import os
import logging
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import field
from enum import StrEnum
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING

from django.conf import settings

from clickhouse_driver import Client as SyncClient
from clickhouse_pool import ChPool

from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from clickhouse_connect.driver import Client as HttpClient

from posthog.clickhouse.workload import Workload
from posthog.settings import data_stores
from posthog.utils import patchable


class NodeRole(StrEnum):
    # Roles of nodes for a particular NodeType. These are meant to
    # match the CH macro hostClusterRole
    ALL = "all"
    DATA = "data"
    INGESTION_EVENTS = "events"
    INGESTION_SMALL = "small"
    INGESTION_MEDIUM = "medium"
    ENDPOINTS = "endpoints"
    LOGS = "logs"

    # Below nodes are part of separate clusters.
    AI_EVENTS = "ai_events"
    AUX = "aux"
    BATCH_EXPORTS = "batch_exports"
    OPS = "ops"
    SESSIONS = "sessions"


# Roles that host replicated MergeTree data; valid ALTER TABLE targets.
# LOGS hosts replicated tables too (metric_series1/metric_samples1 via migration
# 0283); non-sharded ALTERs on it run via any_host_by_roles like the satellites.
DATA_NODE_ROLES: frozenset[NodeRole] = frozenset(
    {
        NodeRole.DATA,
        NodeRole.AI_EVENTS,
        NodeRole.AUX,
        NodeRole.BATCH_EXPORTS,
        NodeRole.LOGS,
        NodeRole.OPS,
        NodeRole.SESSIONS,
    }
)
# Single-shard data clusters: ALTER runs on one host, replication propagates.
SINGLE_SHARD_DATA_NODE_ROLES: frozenset[NodeRole] = frozenset(
    {NodeRole.AI_EVENTS, NodeRole.AUX, NodeRole.BATCH_EXPORTS, NodeRole.OPS, NodeRole.SESSIONS}
)


_default_workload = Workload.ONLINE


class ClickHouseUser(StrEnum):
    # Default, not annotated queries goes here.
    # Avoid using for new queries. We are progressively constraining the resources for this user.
    # Only resort to using during experimentation and development.
    # Once you're past that, create a dedicated user for your product/use-case and use that instead.
    DEFAULT = "default"
    # All /api/ requests called programmatically
    API = "api"
    # All /api/ requests coming from our app
    APP = "app"
    BATCH_EXPORT = "batch_export"
    COHORTS = "cohorts"
    CACHE_WARMUP = "cache_warmup"
    # Whenever the HogQL needs to query CH to get some metadata
    HOGQL = "hogql"  # deprecated, use META
    META = "meta"
    MESSAGING = "messaging"  # a.k.a. behavioral cohorts
    MAX_AI = "max_ai"  # llm/a
    LLM_ANALYTICS = "llm_analytics"  # background AI observability workflows; interactive requests use APP
    # Notebook frame materializations (Temporal worker streaming to the object store)
    NOTEBOOKS = "notebooks"
    ERROR_TRACKING = "error_tracking"
    ENDPOINTS = "endpoints"
    BILLING = "billing"
    REPLAY_VISION = "replay_vision"

    # Backups - used by Dagster backup jobs
    BACKUPS = "backups"
    # Part breaker - used by Dagster part breaking jobs
    PART_BREAKER = "part_breaker"
    # Dev Operations - do not normally use
    OPS = "ops"
    # Only for migrations - do not normally use
    MIGRATIONS = "migrations"
    # Low-privilege reader baked into dictionary SOURCE blocks, decoupling
    # dictionary credentials from the default user.
    DICT_READER = "dict_reader"


@frozen
class ClickHouseCredentials:
    user: str
    password: str = field(repr=False)
    # Path to a file holding the live password. When set, read_password re-reads it on each call,
    # so a rotated short-lived token reaches ClickHouse without rebuilding the pool.
    password_file: str | None = None

    def read_password(self) -> str:
        path = self.password_file
        if path:
            try:
                token = Path(path).read_text().strip()
            except OSError:
                logging.warning("clickhouse: %s is not readable, using the static fallback", path)
                return self.password
            if token:
                return token
            logging.warning("clickhouse: %s is empty, using the static fallback", path)
        return self.password


__user_dict: Mapping[ClickHouseUser, ClickHouseCredentials] | None = None


def init_clickhouse_users() -> Mapping[ClickHouseUser, ClickHouseCredentials]:
    user_dict = {
        ClickHouseUser.DEFAULT: ClickHouseCredentials(
            user=data_stores.CLICKHOUSE_USER,
            password=data_stores.CLICKHOUSE_PASSWORD,
            password_file=data_stores.CLICKHOUSE_PASSWORD_FILE,
        ),
    }
    for u in ClickHouseUser:
        user = os.getenv(f"CLICKHOUSE_{u.name.upper()}_USER")
        password = os.getenv(f"CLICKHOUSE_{u.name.upper()}_PASSWORD")
        password_file = os.getenv(f"CLICKHOUSE_{u.name.upper()}_PASSWORD_FILE")
        secret = password or password_file
        if user and secret:
            user_dict[u] = ClickHouseCredentials(user=user, password=password or "", password_file=password_file)
        elif bool(user) != bool(secret):
            logging.warning(f"only one of clickhouse user/password provided, check your config")
    user_names = ",".join([x.name for x in user_dict.keys()])
    logging.warning(f"initialized clickhouse users: {user_names}")
    return user_dict


def get_clickhouse_creds(user: ClickHouseUser) -> ClickHouseCredentials:
    """
    Retrieve ClickHouse credentials for the specified user.

    This function retrieves the credentials associated with a given ClickHouse
    user. If the specified user is not found, it will fall back to the default
    user credentials.

    The user and password must be properly passed as ENVs:
        CLICKHOUSE_<USER_NAME>_USER
        CLICKHOUSE_<USER_NAME>_PASSWORD

    Args:
        user (ClickHouseUser): The user whose ClickHouse credentials need
                               to be retrieved.
    """
    global __user_dict
    if not __user_dict:
        __user_dict = init_clickhouse_users()
    return __user_dict.get(user, __user_dict[ClickHouseUser.DEFAULT])


class ProxyClient:
    def __init__(self, client: "HttpClient"):
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
            if settings is None:
                settings = {}
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


@cache
def _clickhouse_http_pool_mgr():
    # clickhouse_connect probes pandas/numpy availability when imported, dragging pandas and
    # pyarrow (~400ms) onto the path of whoever imports it — and this module loads at
    # django.setup(). Only the HTTP client paths need it, so build the pool manager on demand.
    from clickhouse_connect.driver import httputil  # noqa: PLC0415

    return httputil.get_pool_manager(
        maxsize=settings.CLICKHOUSE_CONN_POOL_MAX,  # max number of open connection per pool
        block=True,  # makes the maxsize limit per pool, keeps connections
        num_pools=12,  # number of pools
        ca_cert=settings.CLICKHOUSE_CA,
        verify=settings.QUERYSERVICE_VERIFY,
    )


@contextmanager
def get_http_client(**overrides):
    from clickhouse_connect import get_client  # noqa: PLC0415

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
        "pool_mgr": _clickhouse_http_pool_mgr(),
        **overrides,
    }
    yield ProxyClient(get_client(**kwargs))


def get_kwargs_for_client(
    workload: Workload = Workload.DEFAULT,
    team_id=None,
    readonly=False,
    ch_user: ClickHouseUser = ClickHouseUser.DEFAULT,
):
    if workload == Workload.LOGS:
        return {
            "host": settings.CLICKHOUSE_LOGS_CLUSTER_HOST,
            "port": settings.CLICKHOUSE_LOGS_CLUSTER_PORT,
            "database": settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE,
            "user": settings.CLICKHOUSE_LOGS_CLUSTER_USER,
            "password": settings.CLICKHOUSE_LOGS_CLUSTER_PASSWORD,
            "secure": settings.CLICKHOUSE_LOGS_CLUSTER_SECURE,
        }

    creds = get_clickhouse_creds(ch_user)
    base_kwargs = {"user": creds.user, "password": creds.password}

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

    if workload == Workload.ENDPOINTS:
        return {**base_kwargs, "host": settings.CLICKHOUSE_ENDPOINTS_HOST}

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

    if settings.CLICKHOUSE_USE_HTTP or team_id in settings.CLICKHOUSE_USE_HTTP_PER_TEAM:
        # File-backed credential refresh currently covers only the native pool below. This HTTP path
        # (and default_client / ClickhouseCluster) still send the static CLICKHOUSE_*_PASSWORD, so a
        # user must keep its static password until the HTTP path also reads the token file.
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
    creds = get_clickhouse_creds(ch_user)
    # A file-backed user reads its credential fresh on every checkout, so the pool is keyed on
    # identity rather than the rotating credential and stamps the credential in RefreshingChPool.pull.
    # Only when the resolved pool authenticates as this user: the LOGS and readonly paths resolve to
    # their own static credentials and keep a plain pool.
    if creds.password_file and workload != Workload.LOGS and kwargs.get("user") == creds.user:
        kwargs.pop("password", None)
        return make_ch_pool(credential_provider=creds.read_password, **kwargs)
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


class RefreshingChPool(ChPool):
    """ChPool that stamps the current credential onto every pulled client.

    The pool is keyed on identity rather than the credential, so one pool survives credential
    rotation instead of leaking a new pool per rotation. The stamp lands on the client's next
    (re)connect, since ClickHouse authenticates at connection time, not per query: a warm pooled
    connection keeps its session until it is reopened, and the overlapping token TTL covers that gap.
    """

    def __init__(self, *, credential_provider: Callable[[], str], **kwargs) -> None:
        self._credential_provider = credential_provider
        super().__init__(**kwargs)

    def pull(self, key: str | None = None) -> SyncClient:
        client = super().pull(key)
        client.connection.password = self._credential_provider()
        return client


def _make_ch_pool(
    *,
    client_settings: Mapping[str, str] | None = None,
    credential_provider: Callable[[], str] | None = None,
    **overrides,
) -> ChPool:
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

    if credential_provider is not None:
        # kwargs["password"] is only the lazy seed here; RefreshingChPool re-stamps every pulled client.
        return RefreshingChPool(credential_provider=credential_provider, **kwargs)

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
