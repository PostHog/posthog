import pytest

from django.test import override_settings

from products.batch_exports.backend.temporal.clickhouse import ClickHouseEndpoint, resolve_clickhouse_endpoint

MAIN = ClickHouseEndpoint(url="http://main.example.com:8123/", cluster="posthog")
EVENTS = ClickHouseEndpoint(url="http://events.example.com:8123/", cluster="events")


@pytest.mark.parametrize(
    "reads_new_events_table,events_cluster_configured,expected",
    [
        (True, True, EVENTS),
        (False, True, MAIN),
        (True, False, MAIN),
    ],
    ids=["new-table", "legacy-table", "new-table-without-events-cluster"],
)
def test_resolve_clickhouse_endpoint(
    reads_new_events_table: bool,
    events_cluster_configured: bool,
    expected: ClickHouseEndpoint,
):
    with override_settings(
        CLICKHOUSE_OFFLINE_HTTP_URL=MAIN.url,
        CLICKHOUSE_CLUSTER=MAIN.cluster,
        CLICKHOUSE_EVENTS_OFFLINE_HTTP_URL=EVENTS.url if events_cluster_configured else None,
        CLICKHOUSE_EVENTS_CLUSTER=EVENTS.cluster,
        CLICKHOUSE_BATCH_EXPORTS_HTTP_URL=None,
    ):
        endpoint = resolve_clickhouse_endpoint(reads_new_events_table=reads_new_events_table)

    assert endpoint == expected
