from ipaddress import IPv4Address, IPv6Address

import pytest
from unittest.mock import MagicMock, patch

from clickhouse_driver.errors import ServerException

from posthog.clickhouse.client.connection import ClickHouseUser, Workload
from posthog.clickhouse.client.execute import drop_setting_from_query, query_with_columns, sync_execute
from posthog.clickhouse.client.limit import ConcurrencySlot, RateLimit, get_llm_analytics_rate_limiter
from posthog.clickhouse.query_tagging import AccessMethod, Product, tags_context


@pytest.fixture
def client_from_pool():
    with patch("posthog.clickhouse.client.execute.get_client_from_pool") as mock:
        client = MagicMock()
        client.execute.return_value = [(1,)]
        mock.return_value.__enter__.return_value = client
        yield mock


@pytest.fixture
def llm_analytics_slots():
    """Counts concurrency slots taken per query, with the limiter forced on (it is inert in tests)."""
    limiter = get_llm_analytics_rate_limiter()
    with patch.object(limiter, "applicable", lambda *args, **kwargs: True):
        slot = ConcurrencySlot(running_tasks_key="key", task_id="task")
        with patch.object(RateLimit, "use", return_value=slot) as use, patch.object(RateLimit, "release"):
            yield use


@pytest.mark.parametrize(
    "workload,access_method,expected_workload,expected_ch_user",
    [
        (Workload.DEFAULT, None, Workload.ONLINE, ClickHouseUser.APP),
        (Workload.OFFLINE, None, Workload.ONLINE, ClickHouseUser.APP),
        (Workload.LOGS, None, Workload.LOGS, ClickHouseUser.APP),
        (Workload.DEFAULT, AccessMethod.OAUTH, Workload.ONLINE, ClickHouseUser.APP),
        (Workload.DEFAULT, AccessMethod.PERSONAL_API_KEY, Workload.OFFLINE, ClickHouseUser.API),
        (Workload.ONLINE, AccessMethod.PROJECT_SECRET_API_KEY, Workload.OFFLINE, ClickHouseUser.API),
        (Workload.LOGS, AccessMethod.PERSONAL_API_KEY, Workload.LOGS, ClickHouseUser.API),
    ],
)
def test_process_query_task_workload_routing(
    client_from_pool, workload, access_method, expected_workload, expected_ch_user
):
    # The async query worker forces app traffic onto the online cluster while API-key traffic
    # keeps the offline routing it gets when run synchronously. Neither may override
    # cluster-pinned workloads: LOGS-workload tables only exist on the logs cluster.
    with tags_context(kind="celery", id="posthog.tasks.tasks.process_query_task", access_method=access_method):
        sync_execute("SELECT 1", workload=workload, flush=False)

    called_workload, _, _, called_ch_user = client_from_pool.call_args[0]
    assert called_workload == expected_workload
    assert called_ch_user == expected_ch_user


@pytest.mark.parametrize(
    "workload,expected_workload",
    [
        (Workload.DEFAULT, Workload.ENDPOINTS),
        (Workload.LOGS, Workload.LOGS),
    ],
)
def test_endpoints_tag_workload_routing(client_from_pool, workload, expected_workload):
    # The ENDPOINTS tag reroutes queries to the endpoints cluster, but must not override
    # the LOGS cluster pin either.
    with tags_context(kind="request", id="api/endpoint", workload=Workload.ENDPOINTS):
        sync_execute("SELECT 1", workload=workload, flush=False)

    assert client_from_pool.call_args[0][0] == expected_workload


@pytest.mark.parametrize(
    "product,kind,tag_id,requested_ch_user,expected_ch_user",
    [
        (Product.LLM_ANALYTICS, "temporal", "llma-eval-reports", ClickHouseUser.DEFAULT, ClickHouseUser.LLM_ANALYTICS),
        (Product.LLM_ANALYTICS, "request", "api/projects/2/llm_analytics", ClickHouseUser.DEFAULT, ClickHouseUser.APP),
        (Product.WAREHOUSE, "temporal", "data-imports", ClickHouseUser.DEFAULT, ClickHouseUser.DEFAULT),
        # The AI observability usage reports carry this product tag from Celery. The budget is sized
        # for the per-team Temporal fan-out, so they stay off it.
        (Product.LLM_ANALYTICS, "celery", "posthog.tasks.usage_report", ClickHouseUser.DEFAULT, ClickHouseUser.DEFAULT),
        # HogQL's materialized-column lookups name their own user, and must keep it rather than
        # spending a slot of the concurrency budget sized for real queries.
        (Product.LLM_ANALYTICS, "temporal", "llma-eval-reports", ClickHouseUser.HOGQL, ClickHouseUser.HOGQL),
        (Product.LLM_ANALYTICS, "temporal", "llma-eval-reports", ClickHouseUser.META, ClickHouseUser.META),
    ],
)
def test_llm_analytics_ch_user_routing(client_from_pool, product, kind, tag_id, requested_ch_user, expected_ch_user):
    with tags_context(product=product, kind=kind, id=tag_id):
        sync_execute("SELECT 1", flush=False, ch_user=requested_ch_user)

    assert client_from_pool.call_args[0][3] == expected_ch_user


@pytest.mark.parametrize(
    "product,expected_slots",
    [
        (Product.LLM_ANALYTICS, 1),
        (Product.WAREHOUSE, 0),
    ],
)
def test_llm_analytics_queries_take_a_concurrency_slot(client_from_pool, llm_analytics_slots, product, expected_slots):
    # Asserted here rather than at the AI observability call sites because those reach ClickHouse
    # through shared helpers too (query_ai_events, TraceQueryRunner). Holding the slot at this
    # single funnel is what makes the budget cover all of them.
    with tags_context(product=product, kind="temporal", id="llma-eval-reports"):
        sync_execute("SELECT 1", flush=False)

    assert llm_analytics_slots.call_count == expected_slots


@pytest.mark.parametrize(
    "types,row,expected",
    [
        # `system.query_log` grew `connection_address` on top of the two IP columns the
        # callers used to name, and one unserializable value fails the whole API response.
        (
            [("duration", "Float64"), ("connection_address", "IPv6"), ("address", "IPv6")],
            (1.0, IPv6Address("::1"), IPv6Address("::1")),
            {"duration": 1.0},
        ),
        (
            [("duration", "Float64"), ("client", "Nullable(IPv4)")],
            (1.0, IPv4Address("127.0.0.1")),
            {"duration": 1.0},
        ),
        (
            [("duration", "Float64"), ("query", "String")],
            (1.0, "SELECT 1"),
            {"duration": 1.0, "query": "SELECT 1"},
        ),
    ],
)
def test_query_with_columns_removes_columns_by_type(types, row, expected):
    with patch("posthog.clickhouse.client.execute.sync_execute", return_value=([row], types)):
        rows = query_with_columns("SELECT *", column_types_to_remove=("IPv4", "IPv6"))

    assert rows == [expected]


@pytest.mark.parametrize(
    "query,setting,expected",
    [
        # A rejected setting has to come out of the clause without breaking the SQL around it,
        # whatever its position: the retry is only useful if the rewritten query still runs.
        (
            "SELECT 1 SETTINGS readonly=2, optimize_rewrite_aggregate_function_with_if=0, max_threads=4",
            "optimize_rewrite_aggregate_function_with_if",
            "SELECT 1 SETTINGS readonly=2, max_threads=4",
        ),
        ("SELECT 1 SETTINGS readonly=2, max_threads=4", "readonly", "SELECT 1 SETTINGS max_threads=4"),
        ("SELECT 1 SETTINGS readonly=2, max_threads=4", "max_threads", "SELECT 1 SETTINGS readonly=2"),
        # The only setting: the now-empty SETTINGS keyword has to go too, here and in a subquery.
        ("SELECT 1 SETTINGS readonly=2", "readonly", "SELECT 1  "),
        (
            "SELECT * FROM (SELECT 1 SETTINGS optimize_move_to_prewhere = 0) SETTINGS readonly=2",
            "optimize_move_to_prewhere",
            "SELECT * FROM (SELECT 1  ) SETTINGS readonly=2",
        ),
        # A quoted value can hold a comma, so the pair can't be split on one.
        (
            "SELECT 1 SETTINGS force_data_skipping_indices='a, b', readonly=2",
            "force_data_skipping_indices",
            "SELECT 1 SETTINGS readonly=2",
        ),
        ("SELECT 1 SETTINGS readonly=2", "max_threads", "SELECT 1 SETTINGS readonly=2"),
    ],
)
def test_drop_setting_from_query(query, setting, expected):
    assert drop_setting_from_query(query, setting) == expected


def test_unknown_setting_is_retried_without_that_setting(client_from_pool):
    # A node that doesn't know a setting we inject used to kill the query outright, breaking every
    # product on the shared query path at once. The query must survive, minus the setting.
    client = client_from_pool.return_value.__enter__.return_value
    client.execute.side_effect = [
        ServerException("DB::Exception: Unknown setting force_data_skipping_indices", code=115),
        [(1,)],
    ]

    with tags_context(product=Product.PLATFORM_AND_SUPPORT, kind="request", id="test"):
        result = sync_execute("SELECT 1 SETTINGS force_data_skipping_indices='i', readonly=2", flush=False, team_id=1)

    assert result == [(1,)]
    assert client.execute.call_args_list[1].args[0].endswith("SELECT 1 SETTINGS readonly=2")


def test_unknown_setting_we_did_not_send_is_not_retried(client_from_pool):
    # Nothing to drop means the retry would fail identically, so the error has to surface.
    client = client_from_pool.return_value.__enter__.return_value
    client.execute.side_effect = ServerException("DB::Exception: Unknown setting from_a_profile", code=115)

    with tags_context(product=Product.PLATFORM_AND_SUPPORT, kind="request", id="test"), pytest.raises(ServerException):
        sync_execute("SELECT 1 SETTINGS readonly=2", flush=False, team_id=1)

    assert client.execute.call_count == 1
