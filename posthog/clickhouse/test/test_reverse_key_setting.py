import pytest
from unittest.mock import patch

from posthog.clickhouse.logs.logs32 import LOGS32_TABLE_SQL
from posthog.clickhouse.logs.logs34 import LOGS34_TABLE_SQL
from posthog.clickhouse.traces.spans import TRACE_SPANS_TABLE_SQL

# `clickhouse_supports_reverse_key` is imported into each module's namespace, so patch it there.
REVERSE_KEY_GATED_TABLES = [
    ("logs32", "posthog.clickhouse.logs.logs32.clickhouse_supports_reverse_key", LOGS32_TABLE_SQL),
    ("logs34", "posthog.clickhouse.logs.logs34.clickhouse_supports_reverse_key", LOGS34_TABLE_SQL),
    ("trace_spans", "posthog.clickhouse.traces.spans.clickhouse_supports_reverse_key", TRACE_SPANS_TABLE_SQL),
]


@pytest.mark.parametrize(
    "name,gate_path,table_sql", REVERSE_KEY_GATED_TABLES, ids=[t[0] for t in REVERSE_KEY_GATED_TABLES]
)
def test_reverse_key_setting_omitted_on_old_clickhouse(name, gate_path, table_sql):
    # `allow_experimental_reverse_key` only exists in ClickHouse 24.11+; emitting it against an older
    # server aborts migrate_clickhouse. The snapshot suite only exercises the supported (present) path
    # because CI runs a modern ClickHouse, so this locks in the omission on older servers.
    with patch(gate_path, return_value=False):
        assert "allow_experimental_reverse_key" not in table_sql()


def test_reverse_key_gate_defaults_to_supported_when_version_unknown():
    # These builders run at migration-import and pytest-collection time, where ClickHouse may be
    # unreachable. A version-lookup failure must fall back to the historical behavior (setting
    # present) rather than raising, so a dropped try/except can't break SQL generation everywhere.
    from posthog.clickhouse.client.execute import clickhouse_supports_reverse_key

    clickhouse_supports_reverse_key.cache_clear()
    try:
        with patch(
            "posthog.version_requirement.ServiceVersionRequirement.is_service_in_accepted_version",
            side_effect=RuntimeError("clickhouse unreachable"),
        ):
            assert clickhouse_supports_reverse_key() is True
    finally:
        clickhouse_supports_reverse_key.cache_clear()
