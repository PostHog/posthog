import pytest
from unittest.mock import MagicMock, patch

from posthog.clickhouse.client.connection import ClickHouseUser, Workload
from posthog.clickhouse.client.execute import sync_execute
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
