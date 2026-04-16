"""Unit tests for schema_introspect.py.

No live ClickHouse connection required — all tests operate on the pure
functions (_parse_dict_ddl_columns, compare_schemas) or stub out the
cluster object (detect_drift role-grouping).
"""

from collections import namedtuple

import unittest
from unittest.mock import MagicMock

from posthog.clickhouse.migration_tools.schema_introspect import (
    ColumnSchema,
    TableSchema,
    _parse_dict_ddl_columns,
    compare_schemas,
    detect_drift,
)

# ---------------------------------------------------------------------------
# _parse_dict_ddl_columns
# ---------------------------------------------------------------------------


class TestParseDictDdlColumns(unittest.TestCase):
    def _ddl(self, cols: str, prefix: str = "CREATE DICTIONARY db.my_dict") -> str:
        return f"{prefix} ({cols}) SOURCE(...) LAYOUT(HASHED()) LIFETIME(MIN 300 MAX 600)"

    def test_basic_two_columns(self):
        ddl = self._ddl("id UInt64, name String")
        cols = _parse_dict_ddl_columns(ddl)
        self.assertEqual(len(cols), 2)
        self.assertEqual(cols[0].name, "id")
        self.assertEqual(cols[0].type, "UInt64")
        self.assertEqual(cols[1].name, "name")
        self.assertEqual(cols[1].type, "String")

    def test_if_not_exists_variant(self):
        ddl = "CREATE DICTIONARY IF NOT EXISTS db.my_dict (id UInt64, val Float64) SOURCE(...)"
        cols = _parse_dict_ddl_columns(ddl)
        self.assertEqual(len(cols), 2)
        self.assertEqual(cols[0].name, "id")
        self.assertEqual(cols[1].name, "val")

    def test_on_cluster_variant(self):
        ddl = "CREATE DICTIONARY IF NOT EXISTS db.my_dict ON CLUSTER posthog (id UInt64) SOURCE(...)"
        cols = _parse_dict_ddl_columns(ddl)
        self.assertEqual(len(cols), 1)
        self.assertEqual(cols[0].name, "id")

    def test_nullable_nested_type(self):
        ddl = self._ddl("start_date Date, end_date Nullable(Date)")
        cols = _parse_dict_ddl_columns(ddl)
        self.assertEqual(len(cols), 2)
        self.assertEqual(cols[0].type, "Date")
        self.assertEqual(cols[1].type, "Nullable(Date)")

    def test_position_assigned_sequentially(self):
        ddl = self._ddl("a UInt8, b UInt16, c UInt32")
        cols = _parse_dict_ddl_columns(ddl)
        self.assertEqual([c.position for c in cols], [0, 1, 2])

    def test_returns_empty_for_no_match(self):
        self.assertEqual(_parse_dict_ddl_columns("SELECT 1"), [])

    def test_returns_empty_for_unclosed_paren(self):
        self.assertEqual(_parse_dict_ddl_columns("CREATE DICTIONARY db.x (id UInt64"), [])

    def test_backtick_quoted_name(self):
        ddl = self._ddl("`my_col` String")
        cols = _parse_dict_ddl_columns(ddl)
        self.assertEqual(cols[0].name, "my_col")

    def test_strips_codec_clause(self):
        ddl = self._ddl("val String CODEC(ZSTD(3))")
        cols = _parse_dict_ddl_columns(ddl)
        self.assertEqual(cols[0].type, "String")


# ---------------------------------------------------------------------------
# compare_schemas
# ---------------------------------------------------------------------------


def _make_table(name: str, engine: str = "MergeTree", sorting_key: str = "id", **kwargs) -> TableSchema:
    return TableSchema(name=name, engine=engine, sorting_key=sorting_key, **kwargs)


def _make_col(name: str, col_type: str = "String") -> ColumnSchema:
    return ColumnSchema(name=name, type=col_type)


class TestCompareSchemas(unittest.TestCase):
    def test_identical_schemas_produce_no_diffs(self):
        t = _make_table("events")
        t.columns = [_make_col("id", "UInt64"), _make_col("event", "String")]
        self.assertEqual(compare_schemas({"events": t}, {"events": t}), [])

    def test_missing_table(self):
        expected = {"events": _make_table("events")}
        actual: dict[str, TableSchema] = {}
        diffs = compare_schemas(expected, actual)
        self.assertEqual(len(diffs), 1)
        self.assertEqual(diffs[0].diff_type, "missing_table")
        self.assertEqual(diffs[0].table, "events")

    def test_extra_table(self):
        expected: dict[str, TableSchema] = {}
        actual = {"orphan": _make_table("orphan")}
        diffs = compare_schemas(expected, actual)
        self.assertEqual(len(diffs), 1)
        self.assertEqual(diffs[0].diff_type, "extra_table")
        self.assertEqual(diffs[0].table, "orphan")

    def test_engine_mismatch(self):
        exp = _make_table("t", engine="MergeTree")
        act = _make_table("t", engine="ReplicatedMergeTree")
        diffs = compare_schemas({"t": exp}, {"t": act})
        engine_diffs = [d for d in diffs if d.diff_type == "engine_mismatch"]
        self.assertEqual(len(engine_diffs), 1)
        self.assertEqual(engine_diffs[0].expected, "MergeTree")
        self.assertEqual(engine_diffs[0].actual, "ReplicatedMergeTree")

    def test_sorting_key_mismatch(self):
        exp = _make_table("t", sorting_key="id")
        act = _make_table("t", sorting_key="team_id, id")
        diffs = compare_schemas({"t": exp}, {"t": act})
        key_diffs = [d for d in diffs if d.diff_type == "key_mismatch"]
        self.assertEqual(len(key_diffs), 1)

    def test_missing_column(self):
        exp = _make_table("t")
        exp.columns = [_make_col("id"), _make_col("missing_col")]
        act = _make_table("t")
        act.columns = [_make_col("id")]
        diffs = compare_schemas({"t": exp}, {"t": act})
        col_diffs = [d for d in diffs if d.diff_type == "missing_column"]
        self.assertEqual(len(col_diffs), 1)
        self.assertEqual(col_diffs[0].column, "missing_col")

    def test_extra_column(self):
        exp = _make_table("t")
        exp.columns = [_make_col("id")]
        act = _make_table("t")
        act.columns = [_make_col("id"), _make_col("extra_col")]
        diffs = compare_schemas({"t": exp}, {"t": act})
        col_diffs = [d for d in diffs if d.diff_type == "extra_column"]
        self.assertEqual(len(col_diffs), 1)
        self.assertEqual(col_diffs[0].column, "extra_col")

    def test_type_mismatch(self):
        exp = _make_table("t")
        exp.columns = [_make_col("val", "String")]
        act = _make_table("t")
        act.columns = [_make_col("val", "LowCardinality(String)")]
        diffs = compare_schemas({"t": exp}, {"t": act})
        type_diffs = [d for d in diffs if d.diff_type == "type_mismatch"]
        self.assertEqual(len(type_diffs), 1)
        self.assertEqual(type_diffs[0].expected, "String")
        self.assertEqual(type_diffs[0].actual, "LowCardinality(String)")

    def test_dict_layout_mismatch(self):
        exp = _make_table("d", engine="Dictionary")
        exp.dict_layout_type = "HASHED"
        act = _make_table("d", engine="Dictionary")
        act.dict_layout_type = "COMPLEX_KEY_HASHED"
        diffs = compare_schemas({"d": exp}, {"d": act})
        self.assertTrue(any(d.diff_type == "dict_layout_mismatch" for d in diffs))

    def test_dict_source_mismatch(self):
        exp = _make_table("d", engine="Dictionary")
        exp.dict_source_type = "ClickHouse"
        act = _make_table("d", engine="Dictionary")
        act.dict_source_type = "HTTP"
        diffs = compare_schemas({"d": exp}, {"d": act})
        self.assertTrue(any(d.diff_type == "dict_source_mismatch" for d in diffs))

    def test_dict_lifetime_mismatch(self):
        exp = _make_table("d", engine="Dictionary")
        exp.dict_lifetime_min, exp.dict_lifetime_max = 300, 600
        act = _make_table("d", engine="Dictionary")
        act.dict_lifetime_min, act.dict_lifetime_max = 3000, 3600
        diffs = compare_schemas({"d": exp}, {"d": act})
        self.assertTrue(any(d.diff_type == "dict_lifetime_mismatch" for d in diffs))


# ---------------------------------------------------------------------------
# detect_drift — role-grouping logic (no real CH cluster needed)
# ---------------------------------------------------------------------------

_FakeConnInfo = namedtuple("_FakeConnInfo", ["host"])
_FakeHostInfo = namedtuple(
    "_FakeHostInfo",
    ["connection_info", "shard_num", "replica_num", "host_cluster_type", "host_cluster_role"],
)


def _host(hostname: str, role: str | None = "data") -> "_FakeHostInfo":
    return _FakeHostInfo(
        connection_info=_FakeConnInfo(host=hostname),
        shard_num=1,
        replica_num=1,
        host_cluster_type="",
        host_cluster_role=role,
    )


def _mock_cluster(host_schemas: dict) -> MagicMock:
    """Build a ClickhouseCluster mock where map_all_hosts returns host_schemas."""
    cluster = MagicMock()
    future = MagicMock()
    future.result.return_value = host_schemas
    cluster.map_all_hosts.return_value = future
    return cluster


class TestDetectDrift(unittest.TestCase):
    def test_single_host_returns_no_diffs(self):
        h = _host("ch1", role="data")
        schema = {"events": _make_table("events")}
        cluster = _mock_cluster({h: schema})
        self.assertEqual(detect_drift(cluster, "posthog"), [])

    def test_same_role_identical_schemas_no_diffs(self):
        h1, h2 = _host("ch1", "data"), _host("ch2", "data")
        t = _make_table("events")
        t.columns = [_make_col("id", "UInt64")]
        schema = {"events": t}
        cluster = _mock_cluster({h1: schema, h2: schema})
        self.assertEqual(detect_drift(cluster, "posthog"), [])

    def test_same_role_schema_drift_detected(self):
        h1, h2 = _host("ch1", "data"), _host("ch2", "data")
        t1 = _make_table("events")
        t1.columns = [_make_col("id", "UInt64")]
        t2 = _make_table("events")
        t2.columns = [_make_col("id", "UInt64"), _make_col("extra", "String")]
        cluster = _mock_cluster({h1: {"events": t1}, h2: {"events": t2}})
        diffs = detect_drift(cluster, "posthog")
        self.assertTrue(len(diffs) > 0)
        self.assertTrue(any(d.diff_type == "extra_column" for d in diffs))

    def test_different_roles_not_cross_compared(self):
        # DATA and COORDINATOR nodes legitimately have different schemas.
        # detect_drift must NOT compare across role boundaries.
        h_data = _host("ch1", "data")
        h_coord = _host("ch2", "coordinator")
        t_data = _make_table("events")
        t_coord = _make_table("events")
        t_coord.columns = [_make_col("extra", "String")]
        cluster = _mock_cluster({h_data: {"events": t_data}, h_coord: {"events": t_coord}})
        # Each role group has only one host — no intra-group comparison possible.
        self.assertEqual(detect_drift(cluster, "posthog"), [])

    def test_host_label_included_in_diff(self):
        h1, h2 = _host("ch1", "data"), _host("ch2", "data")
        t1 = _make_table("events")
        t2 = _make_table("events")
        t2.engine = "ReplicatedMergeTree"
        cluster = _mock_cluster({h1: {"events": t1}, h2: {"events": t2}})
        diffs = detect_drift(cluster, "posthog")
        self.assertTrue(any("ch2" in d.host for d in diffs))
