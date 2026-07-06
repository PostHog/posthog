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
