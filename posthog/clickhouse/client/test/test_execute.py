import pytest
from unittest.mock import MagicMock, patch

from posthog.clickhouse.client.connection import ClickHouseUser, Workload
from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.query_tagging import tags_context


@pytest.fixture
def client_from_pool():
    with patch("posthog.clickhouse.client.execute.get_client_from_pool") as mock:
        client = MagicMock()
        client.execute.return_value = [(1,)]
        mock.return_value.__enter__.return_value = client
        yield mock


@pytest.mark.parametrize(
    "workload,expected_workload",
    [
        (Workload.DEFAULT, Workload.ONLINE),
        (Workload.OFFLINE, Workload.ONLINE),
        (Workload.LOGS, Workload.LOGS),
    ],
)
def test_process_query_task_workload_routing(client_from_pool, workload, expected_workload):
    # The async query worker forces queries onto the online cluster, but must not override
    # cluster-pinned workloads: LOGS-workload tables only exist on the logs cluster.
    with tags_context(kind="celery", id="posthog.tasks.tasks.process_query_task"):
        sync_execute("SELECT 1", workload=workload, flush=False)

    called_workload, _, _, called_ch_user = client_from_pool.call_args[0]
    assert called_workload == expected_workload
    assert called_ch_user == ClickHouseUser.APP


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
