"""Tests for state_diff convergence — verifying idempotent apply (second run = 0 diffs)."""

from unittest.mock import patch

from posthog.clickhouse.migration_tools.desired_state import ColumnDef, DesiredState, DesiredTable
from posthog.clickhouse.migration_tools.schema_introspect import ColumnSchema, TableSchema
from posthog.clickhouse.migration_tools.state_diff import (
    _generate_create_sql,
    _is_kafka_virtual_column,
    _normalize_default,
    _normalize_interval_funcs,
    _normalize_mv_select,
    _normalize_type,
    _render_dict_layout,
    _render_dict_lifetime,
    _render_dict_source,
    _strip_redundant_parens,
    diff_state,
)

# -- Fix 1: Interval normalization --


class TestNormalizeIntervalFuncs:
    def test_toIntervalDay(self):
        assert _normalize_interval_funcs("today() + toIntervalDay(7)") == "today() + INTERVAL 7 DAY"

    def test_toIntervalHour(self):
        assert _normalize_interval_funcs("now() + toIntervalHour(24)") == "now() + INTERVAL 24 HOUR"

    def test_toIntervalMinute(self):
        assert _normalize_interval_funcs("toIntervalMinute(30)") == "INTERVAL 30 MINUTE"

    def test_toIntervalSecond(self):
        assert _normalize_interval_funcs("toIntervalSecond(60)") == "INTERVAL 60 SECOND"

    def test_toIntervalWeek(self):
        assert _normalize_interval_funcs("toIntervalWeek(2)") == "INTERVAL 2 WEEK"

    def test_toIntervalMonth(self):
        assert _normalize_interval_funcs("toIntervalMonth(1)") == "INTERVAL 1 MONTH"

    def test_toIntervalYear(self):
        assert _normalize_interval_funcs("toIntervalYear(1)") == "INTERVAL 1 YEAR"

    def test_no_change_for_interval_literal(self):
        s = "INTERVAL 7 DAY"
        assert _normalize_interval_funcs(s) == s

    def test_whitespace_in_parens(self):
        assert _normalize_interval_funcs("toIntervalDay(  7  )") == "INTERVAL 7 DAY"

    def test_multiple_intervals(self):
        s = "toIntervalDay(1) + toIntervalHour(2)"
        assert _normalize_interval_funcs(s) == "INTERVAL 1 DAY + INTERVAL 2 HOUR"


class TestNormalizeDefault:
    def test_interval_forms_equivalent(self):
        a = "DEFAULT today() + toIntervalDay(7)"
        b = "DEFAULT today() + INTERVAL 7 DAY"
        assert _normalize_default(a) == _normalize_default(b)

    def test_case_insensitive(self):
        assert _normalize_default("DEFAULT NOW()") == _normalize_default("DEFAULT now()")

    def test_whitespace_collapse(self):
        assert _normalize_default("DEFAULT  now(  )") == _normalize_default("DEFAULT now( )")

    def test_empty_string(self):
        assert _normalize_default("") == ""

    def test_preserves_string_literals(self):
        a = "DEFAULT 'UTC'"
        assert _normalize_default(a) == "default 'utc'"


# -- Fix 2: Kafka virtual columns --


class TestKafkaVirtualColumns:
    def test_known_virtual_columns(self):
        for col in ("_topic", "_key", "_offset", "_partition", "_timestamp", "_headers"):
            assert _is_kafka_virtual_column(col), f"{col} should be virtual"

    def test_headers_dot_prefix(self):
        assert _is_kafka_virtual_column("_headers.name")
        assert _is_kafka_virtual_column("_headers.value")

    def test_regular_column_not_virtual(self):
        assert not _is_kafka_virtual_column("team_id")
        assert not _is_kafka_virtual_column("event")
        assert not _is_kafka_virtual_column("timestamp")


# -- Integration: diff_state convergence --


def _make_desired(tables: dict[str, DesiredTable]) -> DesiredState:
    return DesiredState(ecosystem="test", cluster="test_cluster", tables=tables)


def _col(name: str, type: str, default_kind: str = "", default_expression: str = "") -> ColumnDef:
    return ColumnDef(name=name, type=type, default_kind=default_kind, default_expression=default_expression)


def _live_col(name: str, type: str, default_kind: str = "", default_expression: str = "") -> ColumnSchema:
    return ColumnSchema(name=name, type=type, default_kind=default_kind, default_expression=default_expression)


# Patch _resolve_physical_cluster and _resolve_setting to avoid Django settings dependency
_PATCH_RESOLVE = patch(
    "posthog.clickhouse.migration_tools.state_diff._resolve_physical_cluster",
    return_value="test_cluster",
)
_PATCH_SETTING = patch(
    "posthog.clickhouse.migration_tools.state_diff._resolve_setting",
    side_effect=lambda k: k,
)


class TestDiffConvergenceIntervalDefault:
    """Fix 1: toIntervalDay(7) in YAML should match INTERVAL 7 DAY from system.columns."""

    @_PATCH_RESOLVE
    @_PATCH_SETTING
    def test_no_spurious_alter_for_interval_default(self, _mock_setting, _mock_cluster):
        desired = _make_desired(
            {
                "test_table": DesiredTable(
                    name="test_table",
                    engine="ReplacingMergeTree",
                    columns=[
                        _col("id", "UInt64"),
                        _col(
                            "expires", "Date", default_kind="DEFAULT", default_expression="today() + toIntervalDay(7)"
                        ),
                    ],
                    on_nodes=["all"],
                    order_by=["id"],
                ),
            }
        )
        current = {
            "test_table": TableSchema(
                name="test_table",
                engine="ReplacingMergeTree",
                columns=[
                    _live_col("id", "UInt64"),
                    _live_col("expires", "Date", default_kind="DEFAULT", default_expression="today() + INTERVAL 7 DAY"),
                ],
            ),
        }
        diffs = diff_state(desired, current, database="posthog", cluster="test_cluster")
        assert len(diffs) == 0, f"Expected 0 diffs but got: {[d.detail for d in diffs]}"


class TestDiffConvergenceKafkaVirtualColumns:
    """Fix 2: Kafka virtual columns should not trigger recreate."""

    @_PATCH_RESOLVE
    @_PATCH_SETTING
    def test_no_recreate_when_only_virtual_columns_differ(self, _mock_setting, _mock_cluster):
        desired = _make_desired(
            {
                "kafka_events": DesiredTable(
                    name="kafka_events",
                    engine="Kafka",
                    columns=[
                        _col("event", "String"),
                        _col("timestamp", "DateTime"),
                    ],
                    on_nodes=["all"],
                    settings={"kafka_broker_list": "localhost:9092", "kafka_topic_list": "events"},
                ),
            }
        )
        # Live schema includes virtual columns injected by CH
        current = {
            "kafka_events": TableSchema(
                name="kafka_events",
                engine="Kafka",
                columns=[
                    _live_col("event", "String"),
                    _live_col("timestamp", "DateTime"),
                    _live_col("_topic", "LowCardinality(String)"),
                    _live_col("_key", "String"),
                    _live_col("_offset", "UInt64"),
                    _live_col("_partition", "UInt64"),
                    _live_col("_timestamp", "Nullable(DateTime)"),
                    _live_col("_headers", "Map(String, String)"),
                ],
            ),
        }
        diffs = diff_state(desired, current, database="posthog", cluster="test_cluster")
        assert len(diffs) == 0, f"Expected 0 diffs but got: {[d.detail for d in diffs]}"


class TestDiffConvergenceDistributedEmptyColumns:
    """Fix 4: Distributed tables with columns: [] should not generate column diffs."""

    @_PATCH_RESOLVE
    @_PATCH_SETTING
    def test_no_drop_columns_for_empty_desired(self, _mock_setting, _mock_cluster):
        desired = _make_desired(
            {
                "events_dist": DesiredTable(
                    name="events_dist",
                    engine="Distributed",
                    columns=[],  # inherit from source
                    on_nodes=["all"],
                    source="sharded_events",
                ),
            }
        )
        # Live schema has real columns (inherited from source at creation time)
        current = {
            "events_dist": TableSchema(
                name="events_dist",
                engine="Distributed",
                columns=[
                    _live_col("uuid", "UUID"),
                    _live_col("event", "String"),
                    _live_col("timestamp", "DateTime"),
                ],
            ),
        }
        diffs = diff_state(desired, current, database="posthog", cluster="test_cluster")
        # Should not produce DROP COLUMN diffs
        drop_diffs = [d for d in diffs if "drop_column" in d.action.lower() or "Drop column" in d.detail]
        assert len(drop_diffs) == 0, f"Expected no column drops but got: {[d.detail for d in drop_diffs]}"


class TestDiffConvergenceKafkaMVStability:
    """Fix 3: Kafka table not being recreated means its MV stays stable too."""

    @_PATCH_RESOLVE
    @_PATCH_SETTING
    def test_kafka_and_mv_stable_on_second_apply(self, _mock_setting, _mock_cluster):
        desired = _make_desired(
            {
                "kafka_events": DesiredTable(
                    name="kafka_events",
                    engine="Kafka",
                    columns=[
                        _col("event", "String"),
                    ],
                    on_nodes=["all"],
                    settings={"kafka_broker_list": "localhost:9092", "kafka_topic_list": "events"},
                ),
                "kafka_events_mv": DesiredTable(
                    name="kafka_events_mv",
                    engine="MaterializedView",
                    columns=[],
                    on_nodes=["all"],
                    target="sharded_events",
                    select="SELECT event FROM posthog.kafka_events",
                ),
            }
        )
        current = {
            "kafka_events": TableSchema(
                name="kafka_events",
                engine="Kafka",
                columns=[
                    _live_col("event", "String"),
                    _live_col("_topic", "LowCardinality(String)"),
                    _live_col("_offset", "UInt64"),
                ],
            ),
            "kafka_events_mv": TableSchema(
                name="kafka_events_mv",
                engine="MaterializedView",
                as_select="SELECT event FROM posthog.kafka_events",
                columns=[
                    _live_col("event", "String"),
                ],
            ),
        }
        diffs = diff_state(desired, current, database="posthog", cluster="test_cluster")
        assert len(diffs) == 0, f"Expected 0 diffs but got: {[d.detail for d in diffs]}"


# -- Fix 1: Lambda condition parenthesization normalization --


class TestNormalizeLambdaParens:
    def test_lambda_parens_stripped(self):
        a = "mapFilter((key, _) -> (key NOT LIKE '$%'), m)"
        b = "mapFilter((key, _) -> key NOT LIKE '$%', m)"
        assert _normalize_default(a) == _normalize_default(b)

    def test_lambda_nested_parens_preserved(self):
        a = "arrayMap((x) -> (toInt64(x) + 1), arr)"
        b = "arrayMap((x) -> toInt64(x) + 1, arr)"
        assert _normalize_default(a) == _normalize_default(b)

    def test_lambda_no_parens_unchanged(self):
        a = "arrayMap((x) -> x + 1, arr)"
        assert _normalize_default(a) == _normalize_default(a)


# -- Fix 2: Enum8/Enum16 type normalization --


class TestNormalizeType:
    def test_enum8_to_enum(self):
        assert _normalize_type("Enum8('a' = 1, 'button' = 2)") == "Enum('a', 'button')"

    def test_enum16_to_enum(self):
        assert _normalize_type("Enum16('x' = 100, 'y' = 200)") == "Enum('x', 'y')"

    def test_array_enum8(self):
        assert _normalize_type("Array(Enum8('a' = 1, 'button' = 2))") == "Array(Enum('a', 'button'))"

    def test_plain_enum_unchanged(self):
        assert _normalize_type("Enum('a', 'b')") == "Enum('a', 'b')"

    def test_non_enum_unchanged(self):
        assert _normalize_type("String") == "String"


class TestDiffConvergenceEnum8:
    @_PATCH_RESOLVE
    @_PATCH_SETTING
    def test_no_alter_for_enum8_vs_enum(self, _mock_setting, _mock_cluster):
        desired = _make_desired(
            {
                "test_table": DesiredTable(
                    name="test_table",
                    engine="ReplacingMergeTree",
                    columns=[
                        _col("id", "UInt64"),
                        _col("status", "Enum('active', 'deleted')"),
                    ],
                    on_nodes=["all"],
                    order_by=["id"],
                ),
            }
        )
        current = {
            "test_table": TableSchema(
                name="test_table",
                engine="ReplacingMergeTree",
                columns=[
                    _live_col("id", "UInt64"),
                    _live_col("status", "Enum8('active' = 1, 'deleted' = 2)"),
                ],
            ),
        }
        diffs = diff_state(desired, current, database="posthog", cluster="test_cluster")
        assert len(diffs) == 0, f"Expected 0 diffs but got: {[d.detail for d in diffs]}"


# -- Fix 3: Quote escaping normalization --


class TestNormalizeQuoteEscaping:
    def test_double_backslash_quote(self):
        a = 'DEFAULT \\\\"hello\\\\"'
        b = 'DEFAULT "hello"'
        assert _normalize_default(a) == _normalize_default(b)

    def test_single_backslash_quote(self):
        a = 'DEFAULT \\"hello\\"'
        b = 'DEFAULT "hello"'
        assert _normalize_default(a) == _normalize_default(b)


# -- Fix 4: DateTime64 precision and Decimal type aliases --


class TestNormalizeDateTime64:
    def test_datetime64_default_precision(self):
        assert _normalize_type("DateTime64") == "DateTime64(3)"

    def test_datetime64_explicit_3(self):
        assert _normalize_type("DateTime64(3)") == "DateTime64(3)"

    def test_datetime64_explicit_6(self):
        assert _normalize_type("DateTime64(6)") == "DateTime64(6)"

    def test_nullable_datetime64(self):
        assert _normalize_type("Nullable(DateTime64)") == "Nullable(DateTime64(3))"


class TestNormalizeDecimal:
    def test_decimal_18_10_to_decimal64(self):
        assert _normalize_type("Decimal(18, 10)") == "Decimal64(10)"

    def test_decimal_9_2_to_decimal32(self):
        assert _normalize_type("Decimal(9, 2)") == "Decimal32(2)"

    def test_decimal_38_10_to_decimal128(self):
        assert _normalize_type("Decimal(38, 10)") == "Decimal128(10)"

    def test_decimal64_unchanged(self):
        assert _normalize_type("Decimal64(10)") == "Decimal64(10)"


class TestDiffConvergenceDateTime64:
    @_PATCH_RESOLVE
    @_PATCH_SETTING
    def test_no_alter_datetime64_vs_datetime64_3(self, _mock_setting, _mock_cluster):
        desired = _make_desired(
            {
                "test_table": DesiredTable(
                    name="test_table",
                    engine="ReplacingMergeTree",
                    columns=[
                        _col("id", "UInt64"),
                        _col("created_at", "DateTime64(3)"),
                    ],
                    on_nodes=["all"],
                    order_by=["id"],
                ),
            }
        )
        current = {
            "test_table": TableSchema(
                name="test_table",
                engine="ReplacingMergeTree",
                columns=[
                    _live_col("id", "UInt64"),
                    _live_col("created_at", "DateTime64"),
                ],
            ),
        }
        diffs = diff_state(desired, current, database="posthog", cluster="test_cluster")
        assert len(diffs) == 0, f"Expected 0 diffs but got: {[d.detail for d in diffs]}"


# -- Fix 5: Kafka/MV recreate cascade prevention --


class TestKafkaMVCascadePrevention:
    @_PATCH_RESOLVE
    @_PATCH_SETTING
    def test_kafka_recreated_after_mv_recreate(self, _mock_setting, _mock_cluster):
        desired = _make_desired(
            {
                "kafka_events": DesiredTable(
                    name="kafka_events",
                    engine="Kafka",
                    columns=[_col("event", "String")],
                    on_nodes=["all"],
                    settings={"kafka_broker_list": "localhost:9092", "kafka_topic_list": "events"},
                ),
                "sharded_events": DesiredTable(
                    name="sharded_events",
                    engine="ReplacingMergeTree",
                    columns=[_col("event", "String")],
                    on_nodes=["all"],
                    order_by=["event"],
                ),
                "kafka_events_mv": DesiredTable(
                    name="kafka_events_mv",
                    engine="MaterializedView",
                    columns=[],
                    on_nodes=["all"],
                    target="sharded_events",
                    select="SELECT event FROM posthog.kafka_events",
                ),
            }
        )
        # Current state: MV target changed → triggers recreate_mv
        current = {
            "kafka_events": TableSchema(
                name="kafka_events",
                engine="Kafka",
                columns=[_live_col("event", "String")],
            ),
            "sharded_events": TableSchema(
                name="sharded_events",
                engine="ReplacingMergeTree",
                columns=[_live_col("event", "String")],
            ),
            "kafka_events_mv": TableSchema(
                name="kafka_events_mv",
                engine="MaterializedView",
                engine_full="MaterializedView TO posthog.old_target",
                as_select="SELECT event FROM posthog.kafka_events",
                columns=[_live_col("event", "String")],
            ),
        }
        diffs = diff_state(desired, current, database="posthog", cluster="test_cluster")
        # Should have a recreate_mv for the MV
        mv_recreates = [d for d in diffs if d.action == "recreate_mv"]
        assert len(mv_recreates) == 1, f"Expected 1 MV recreate but got: {[d.detail for d in mv_recreates]}"
        # Should have a create step for the Kafka table (cascade prevention)
        kafka_creates = [d for d in diffs if d.action == "create" and d.table == "kafka_events"]
        assert len(kafka_creates) == 1, f"Expected Kafka re-create but got: {[d.detail for d in kafka_creates]}"
        assert "cascade" in kafka_creates[0].detail.lower()


# -- Bug A: Nested AND/OR parens in lambda bodies --


class TestStripRedundantParens:
    def test_outer_lambda_parens(self):
        assert _strip_redundant_parens("-> (x + 1)") == "-> x + 1"

    def test_nested_and_operand_parens(self):
        s = "-> ((key like '$ai_%') and (key not in ('a', 'b')))"
        result = _strip_redundant_parens(s)
        assert "(" not in result.split("->")[1].split("not in")[0], f"Redundant parens remain: {result}"
        assert "key like '$ai_%' and key not in" in result

    def test_or_operand_parens(self):
        s = "-> ((a > 1) or (b < 2))"
        result = _strip_redundant_parens(s)
        assert result == "-> a > 1 or b < 2"

    def test_preserves_function_call_parens(self):
        s = "-> toInt64(x) + 1"
        assert _strip_redundant_parens(s) == s

    def test_stable_on_already_clean(self):
        s = "-> key like '$ai_%' and key not in ('a', 'b')"
        assert _strip_redundant_parens(s) == s


class TestNormalizeDefaultNestedLambdaParens:
    def test_ch_style_vs_yaml_style(self):
        ch = "DEFAULT mapFilter((key, _) -> ((key LIKE '$ai_%') AND (key NOT IN ('$ai_generation_id'))), m)"
        yaml = "DEFAULT mapFilter((key, _) -> key LIKE '$ai_%' AND key NOT IN ('$ai_generation_id'), m)"
        assert _normalize_default(ch) == _normalize_default(yaml)

    def test_triple_and(self):
        ch = "DEFAULT mapFilter((k, v) -> ((k LIKE 'a%') AND (k NOT LIKE 'b%') AND (v != '')), m)"
        yaml = "DEFAULT mapFilter((k, v) -> k LIKE 'a%' AND k NOT LIKE 'b%' AND v != '', m)"
        assert _normalize_default(ch) == _normalize_default(yaml)


# -- Bug B: MV SELECT body normalization --


class TestNormalizeMvSelect:
    def test_database_prefix_stripped(self):
        ch = "SELECT event FROM posthog_test.kafka_events"
        yaml = "SELECT event FROM kafka_events"
        assert _normalize_mv_select(ch) == _normalize_mv_select(yaml)

    def test_keyword_case_normalized(self):
        ch = "SELECT event FROM kafka_events WHERE team_id = 1"
        yaml = "select event from kafka_events where team_id = 1"
        assert _normalize_mv_select(ch) == _normalize_mv_select(yaml)

    def test_trailing_settings_stripped(self):
        ch = "SELECT event FROM kafka_events SETTINGS max_threads = 4"
        yaml = "SELECT event FROM kafka_events"
        assert _normalize_mv_select(ch) == _normalize_mv_select(yaml)

    def test_whitespace_collapsed(self):
        ch = "SELECT  event\n  FROM   kafka_events"
        yaml = "SELECT event FROM kafka_events"
        assert _normalize_mv_select(ch) == _normalize_mv_select(yaml)

    def test_combined_differences(self):
        ch = "SELECT event, timestamp AS ts FROM posthog_test.kafka_events WHERE team_id = 1 SETTINGS max_threads = 4"
        yaml = "select event, timestamp as ts from kafka_events where team_id = 1"
        assert _normalize_mv_select(ch) == _normalize_mv_select(yaml)

    def test_multiple_db_prefixes(self):
        ch = "SELECT a FROM posthog.t1 JOIN posthog.t2 ON t1.id = t2.id"
        yaml = "SELECT a FROM t1 JOIN t2 ON t1.id = t2.id"
        assert _normalize_mv_select(ch) == _normalize_mv_select(yaml)


class TestDiffConvergenceMvSelect:
    @_PATCH_RESOLVE
    @_PATCH_SETTING
    def test_no_recreate_when_only_db_prefix_differs(self, _mock_setting, _mock_cluster):
        desired = _make_desired(
            {
                "events_mv": DesiredTable(
                    name="events_mv",
                    engine="MaterializedView",
                    columns=[],
                    on_nodes=["all"],
                    target="sharded_events",
                    select="SELECT event FROM kafka_events",
                ),
            }
        )
        current = {
            "events_mv": TableSchema(
                name="events_mv",
                engine="MaterializedView",
                as_select="SELECT event FROM posthog_test.kafka_events",
                columns=[_live_col("event", "String")],
            ),
        }
        diffs = diff_state(desired, current, database="posthog", cluster="test_cluster")
        assert len(diffs) == 0, f"Expected 0 diffs but got: {[d.detail for d in diffs]}"

    @_PATCH_RESOLVE
    @_PATCH_SETTING
    def test_no_recreate_when_keyword_case_and_settings_differ(self, _mock_setting, _mock_cluster):
        desired = _make_desired(
            {
                "events_mv": DesiredTable(
                    name="events_mv",
                    engine="MaterializedView",
                    columns=[],
                    on_nodes=["all"],
                    target="sharded_events",
                    select="SELECT event FROM kafka_events WHERE team_id = 1",
                ),
            }
        )
        current = {
            "events_mv": TableSchema(
                name="events_mv",
                engine="MaterializedView",
                as_select="SELECT event FROM posthog.kafka_events WHERE team_id = 1 SETTINGS max_threads = 4",
                columns=[_live_col("event", "String")],
            ),
        }
        diffs = diff_state(desired, current, database="posthog", cluster="test_cluster")
        assert len(diffs) == 0, f"Expected 0 diffs but got: {[d.detail for d in diffs]}"


# -- Dictionary engine support --


def _dict_table(
    name: str = "channel_definition_dict",
    primary_key: str = "domain, kind",
) -> DesiredTable:
    return DesiredTable(
        name=name,
        engine="Dictionary",
        columns=[
            _col("domain", "String"),
            _col("kind", "String"),
            _col("domain_type", "Nullable(String)"),
        ],
        on_nodes=["ALL"],
        primary_key=primary_key,
        dict_source={"type": "CLICKHOUSE", "table": "channel_definition", "password": "secret"},
        dict_layout={"type": "COMPLEX_KEY_HASHED"},
        dict_lifetime={"min": 3000, "max": 3600},
    )


class TestRenderDictSource:
    def test_clickhouse_source(self):
        s = _render_dict_source({"type": "CLICKHOUSE", "table": "channel_definition", "password": "secret"})
        assert s == "SOURCE(CLICKHOUSE(table 'channel_definition' password 'secret'))"

    def test_http_source(self):
        s = _render_dict_source({"type": "HTTP", "url": "https://example.com/x.csv", "format": "CSVWithNames"})
        assert s == "SOURCE(HTTP(url 'https://example.com/x.csv' format 'CSVWithNames'))"

    def test_from_settings_sentinel_resolves(self):
        with patch(
            "posthog.clickhouse.migration_tools.state_diff._resolve_setting",
            side_effect=lambda k: f"RESOLVED_{k}",
        ):
            s = _render_dict_source({"type": "CLICKHOUSE", "table": "x", "password": "__from_settings__"})
        assert "password 'RESOLVED_password'" in s

    def test_settings_resolution_keys_match_yaml_param_names(self):
        """Regression: `password`/`user` keys in `_SETTINGS_RESOLUTION` must equal the
        YAML parameter names. Otherwise `_resolve_setting('password')` misses the map
        and falls back to the kafka placeholder, leaking that into the SOURCE clause.
        """
        from posthog.clickhouse.migration_tools.state_diff import _SETTINGS_RESOLUTION

        assert "password" in _SETTINGS_RESOLUTION, "YAML key 'password' must be a resolution-map key"
        assert "user" in _SETTINGS_RESOLUTION, "YAML key 'user' must be a resolution-map key"

    def test_missing_type_raises(self):
        try:
            _render_dict_source({"table": "x"})
        except ValueError as e:
            assert "type" in str(e)
        else:
            raise AssertionError("expected ValueError")


class TestRenderDictLayout:
    def test_no_params(self):
        assert _render_dict_layout({"type": "COMPLEX_KEY_HASHED"}) == "LAYOUT(COMPLEX_KEY_HASHED())"

    def test_with_params(self):
        s = _render_dict_layout({"type": "RANGE_HASHED", "params": {"range_lookup_strategy": "max"}})
        assert s == "LAYOUT(RANGE_HASHED(range_lookup_strategy 'max'))"

    def test_missing_type_raises(self):
        try:
            _render_dict_layout({})
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError")


class TestRenderDictLifetime:
    def test_basic(self):
        assert _render_dict_lifetime({"min": 3000, "max": 3600}) == "LIFETIME(MIN 3000 MAX 3600)"

    def test_missing_raises(self):
        try:
            _render_dict_lifetime({"min": 10})
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError")


class TestDictionaryEngine:
    def test_parse_dictionary_yaml(self, tmp_path):
        """YAML with full Dictionary metadata parses into DesiredTable."""
        yaml_path = tmp_path / "test_dict.yaml"
        yaml_path.write_text(
            """
ecosystem: test
cluster: main
tables:
  channel_definition_dict:
    engine: Dictionary
    on_nodes: ALL
    primary_key: domain, kind
    columns:
      - name: domain
        type: String
      - name: kind
        type: String
    source:
      type: CLICKHOUSE
      table: channel_definition
      password: __from_settings__
    layout:
      type: COMPLEX_KEY_HASHED
    lifetime:
      min: 3000
      max: 3600
"""
        )
        from posthog.clickhouse.migration_tools.desired_state import parse_desired_state

        state = parse_desired_state(yaml_path)
        t = state.tables["channel_definition_dict"]
        assert t.engine == "Dictionary"
        assert t.primary_key == "domain, kind"
        assert t.dict_source == {"type": "CLICKHOUSE", "table": "channel_definition", "password": "__from_settings__"}
        assert t.dict_layout == {"type": "COMPLEX_KEY_HASHED"}
        assert t.dict_lifetime == {"min": 3000, "max": 3600}
        # Dictionary `source` must not leak into the Distributed `source` field
        assert t.source is None

    def test_generate_dictionary_create_sql(self):
        sql = _generate_create_sql(_dict_table(), "posthog", "main")
        assert sql.startswith("CREATE DICTIONARY IF NOT EXISTS posthog.channel_definition_dict")
        assert "PRIMARY KEY domain, kind" in sql
        assert "SOURCE(CLICKHOUSE(table 'channel_definition' password 'secret'))" in sql
        assert "LAYOUT(COMPLEX_KEY_HASHED())" in sql
        assert "LIFETIME(MIN 3000 MAX 3600)" in sql

    def test_generate_dictionary_sql_missing_primary_key_raises(self):
        t = _dict_table()
        t.primary_key = None
        try:
            _generate_create_sql(t, "posthog", "main")
        except ValueError as e:
            assert "primary_key" in str(e)
        else:
            raise AssertionError("expected ValueError")

    @_PATCH_RESOLVE
    @_PATCH_SETTING
    def test_dictionary_create_emitted_when_missing(self, _mock_setting, _mock_cluster):
        """Dictionary in desired but not in current produces a CREATE DICTIONARY diff."""
        desired = _make_desired({"channel_definition_dict": _dict_table()})
        diffs = diff_state(desired, {}, database="posthog", cluster="test_cluster")
        creates = [d for d in diffs if d.action == "create"]
        assert len(creates) == 1
        assert creates[0].table == "channel_definition_dict"
        assert "CREATE DICTIONARY" in creates[0].sql

    @_PATCH_RESOLVE
    @_PATCH_SETTING
    def test_dictionary_drop_uses_drop_dictionary_verb(self, _mock_setting, _mock_cluster):
        """Extraneous Dictionary in current → drops with DROP DICTIONARY IF EXISTS."""
        desired = _make_desired({})
        current = {
            "stray_dict": TableSchema(
                name="stray_dict",
                engine="Dictionary",
                columns=[_live_col("k", "String")],
            )
        }
        diffs = diff_state(desired, current, database="posthog", cluster="test_cluster")
        drops = [d for d in diffs if d.action == "drop"]
        assert len(drops) == 1
        assert "DROP DICTIONARY IF EXISTS posthog.stray_dict" in drops[0].sql

    @_PATCH_RESOLVE
    @_PATCH_SETTING
    def test_dictionary_diff_generates_drop_create_on_column_change(self, _mock_setting, _mock_cluster):
        """Dictionaries can't ALTER — a column change must emit DROP DICTIONARY + CREATE DICTIONARY."""
        desired = _make_desired({"channel_definition_dict": _dict_table()})
        current = {
            "channel_definition_dict": TableSchema(
                name="channel_definition_dict",
                engine="Dictionary",
                engine_full=(
                    "Dictionary PRIMARY KEY domain, kind "
                    "SOURCE(CLICKHOUSE(TABLE 'channel_definition' PASSWORD 'x')) "
                    "LAYOUT(COMPLEX_KEY_HASHED()) LIFETIME(MIN 3000 MAX 3600)"
                ),
                columns=[
                    _live_col("domain", "String"),
                    _live_col("kind", "String"),
                    # Missing `domain_type` → triggers DROP + CREATE
                ],
            )
        }
        diffs = diff_state(desired, current, database="posthog", cluster="test_cluster")
        drops = [d for d in diffs if d.action == "drop"]
        creates = [d for d in diffs if d.action == "create"]
        assert len(drops) == 1
        assert "DROP DICTIONARY IF EXISTS posthog.channel_definition_dict" in drops[0].sql
        assert len(creates) == 1
        assert "CREATE DICTIONARY" in creates[0].sql

    @_PATCH_RESOLVE
    @_PATCH_SETTING
    def test_dictionary_stable_when_matching(self, _mock_setting, _mock_cluster):
        """Dictionary with matching columns + engine_full metadata → 0 diffs (convergence)."""
        desired = _make_desired({"channel_definition_dict": _dict_table()})
        current = {
            "channel_definition_dict": TableSchema(
                name="channel_definition_dict",
                engine="Dictionary",
                engine_full=(
                    "Dictionary PRIMARY KEY domain, kind "
                    "SOURCE(CLICKHOUSE(TABLE 'channel_definition' PASSWORD 'x')) "
                    "LAYOUT(COMPLEX_KEY_HASHED()) LIFETIME(MIN 3000 MAX 3600)"
                ),
                columns=[
                    _live_col("domain", "String"),
                    _live_col("kind", "String"),
                    _live_col("domain_type", "Nullable(String)"),
                ],
            )
        }
        diffs = diff_state(desired, current, database="posthog", cluster="test_cluster")
        assert len(diffs) == 0, f"Expected 0 diffs but got: {[d.detail for d in diffs]}"

    @_PATCH_RESOLVE
    @_PATCH_SETTING
    def test_dictionary_recreate_on_lifetime_change(self, _mock_setting, _mock_cluster):
        """LIFETIME metadata change forces DROP + CREATE (Dictionaries don't ALTER)."""
        desired = _make_desired({"channel_definition_dict": _dict_table()})
        current = {
            "channel_definition_dict": TableSchema(
                name="channel_definition_dict",
                engine="Dictionary",
                # Stored lifetime differs from desired (300/600 vs 3000/3600)
                engine_full=(
                    "Dictionary PRIMARY KEY domain, kind "
                    "SOURCE(CLICKHOUSE(TABLE 'channel_definition' PASSWORD 'x')) "
                    "LAYOUT(COMPLEX_KEY_HASHED()) LIFETIME(MIN 300 MAX 600)"
                ),
                columns=[
                    _live_col("domain", "String"),
                    _live_col("kind", "String"),
                    _live_col("domain_type", "Nullable(String)"),
                ],
            )
        }
        diffs = diff_state(desired, current, database="posthog", cluster="test_cluster")
        recreates = [d for d in diffs if d.action == "recreate"]
        assert len(recreates) == 1
        assert "DROP DICTIONARY IF EXISTS posthog.channel_definition_dict" in recreates[0].sql
        assert "CREATE DICTIONARY" in recreates[0].sql
        assert "LIFETIME" in recreates[0].detail


# -- P1-C: Distributed source with database prefix --------------------------


class TestDistributedSourceWithDbPrefix:
    """P1-C: Distributed(..., '<db>', '<table>', ...) must split source on '.'.

    YAML `source: system.processes` must produce `Distributed(..., 'system',
    'processes', ...)`. Passing the full string as the table name makes CH
    resolve `system.processes` in the local database, which fails.
    """

    @_PATCH_RESOLVE
    @_PATCH_SETTING
    def test_system_processes_split_into_db_and_table(self, _mock_setting, _mock_cluster):
        table = DesiredTable(
            name="distributed_system_processes",
            engine="Distributed",
            columns=[],
            on_nodes=["all"],
            source="system.processes",
        )
        sql = _generate_create_sql(table, "posthog_test", "test_cluster")

        assert "'system', 'processes'" in sql, f"Expected 'system', 'processes' in: {sql}"
        # Must NOT emit the un-split form that CH resolves to the current DB.
        assert "'posthog_test', 'system.processes'" not in sql
        # AS clause still references the qualified source so columns inherit.
        assert "AS system.processes" in sql

    @_PATCH_RESOLVE
    @_PATCH_SETTING
    def test_undotted_source_uses_current_database(self, _mock_setting, _mock_cluster):
        table = DesiredTable(
            name="events_dist",
            engine="Distributed",
            columns=[_col("uuid", "UUID")],
            on_nodes=["all"],
            source="sharded_events",
        )
        sql = _generate_create_sql(table, "posthog", "test_cluster")

        assert "'posthog', 'sharded_events'" in sql


# -- P1-B: Kafka cascade on MV drop+create pair -----------------------------


class TestKafkaCascadeOnSelectChange:
    """P1-B: When an MV's SELECT changes, the diff emits drop+create rather
    than recreate_mv. The cascade fix must still re-create the Kafka source.
    """

    @_PATCH_RESOLVE
    @_PATCH_SETTING
    def test_kafka_recreated_on_mv_select_change(self, _mock_setting, _mock_cluster):
        desired = _make_desired(
            {
                "kafka_events": DesiredTable(
                    name="kafka_events",
                    engine="Kafka",
                    columns=[_col("event", "String")],
                    on_nodes=["all"],
                    settings={"kafka_broker_list": "localhost:9092", "kafka_topic_list": "events"},
                ),
                "kafka_events_mv": DesiredTable(
                    name="kafka_events_mv",
                    engine="MaterializedView",
                    columns=[],
                    on_nodes=["all"],
                    target="sharded_events",
                    select="SELECT event, toUnixTimestamp(timestamp) AS ts FROM posthog.kafka_events",
                ),
            }
        )
        current = {
            "kafka_events": TableSchema(
                name="kafka_events",
                engine="Kafka",
                columns=[
                    _live_col("event", "String"),
                    _live_col("_topic", "LowCardinality(String)"),
                ],
            ),
            "kafka_events_mv": TableSchema(
                name="kafka_events_mv",
                engine="MaterializedView",
                # Old SELECT — triggers the drop+create path (not recreate_mv)
                as_select="SELECT event FROM posthog.kafka_events",
                columns=[_live_col("event", "String")],
            ),
        }
        diffs = diff_state(desired, current, database="posthog", cluster="test_cluster")

        # Verify MV got a drop+create (not recreate_mv)
        mv_drops = [d for d in diffs if d.action == "drop" and d.table == "kafka_events_mv"]
        mv_creates = [d for d in diffs if d.action == "create" and d.table == "kafka_events_mv"]
        assert len(mv_drops) == 1, f"Expected MV drop; got {[d.detail for d in diffs]}"
        assert len(mv_creates) == 1, f"Expected MV create; got {[d.detail for d in diffs]}"

        # Cascade fix must add a create for the Kafka source
        kafka_creates = [d for d in diffs if d.action == "create" and d.table == "kafka_events"]
        assert len(kafka_creates) == 1, (
            f"Expected Kafka source to be re-added after MV recreate; got {[d.detail for d in diffs]}"
        )
        assert "cascade-dropped" in kafka_creates[0].detail.lower()

    @_PATCH_RESOLVE
    @_PATCH_SETTING
    def test_no_cascade_when_mv_stable(self, _mock_setting, _mock_cluster):
        """Regression: Kafka is not re-added when the MV isn't being recreated."""
        desired = _make_desired(
            {
                "kafka_events": DesiredTable(
                    name="kafka_events",
                    engine="Kafka",
                    columns=[_col("event", "String")],
                    on_nodes=["all"],
                    settings={"kafka_broker_list": "localhost:9092", "kafka_topic_list": "events"},
                ),
                "kafka_events_mv": DesiredTable(
                    name="kafka_events_mv",
                    engine="MaterializedView",
                    columns=[],
                    on_nodes=["all"],
                    target="sharded_events",
                    select="SELECT event FROM posthog.kafka_events",
                ),
            }
        )
        current = {
            "kafka_events": TableSchema(
                name="kafka_events",
                engine="Kafka",
                columns=[
                    _live_col("event", "String"),
                    _live_col("_topic", "LowCardinality(String)"),
                ],
            ),
            "kafka_events_mv": TableSchema(
                name="kafka_events_mv",
                engine="MaterializedView",
                as_select="SELECT event FROM posthog.kafka_events",
                columns=[_live_col("event", "String")],
            ),
        }
        diffs = diff_state(desired, current, database="posthog", cluster="test_cluster")
        kafka_creates = [d for d in diffs if d.action == "create" and d.table == "kafka_events"]
        assert len(kafka_creates) == 0, f"Unexpected Kafka recreate: {[d.detail for d in diffs]}"

# -- Dictionary introspection + extended recreate checks --


class TestDumpDictionaries:
    def test_enriches_existing_table_schema(self):
        """dump_dictionaries populates dict_* fields on the matching TableSchema."""
        from posthog.clickhouse.migration_tools.schema_introspect import TableSchema, dump_dictionaries

        schema = {
            "channel_definition_dict": TableSchema(
                name="channel_definition_dict",
                engine="Dictionary",
            )
        }

        class _FakeClient:
            def execute(self, query, params):
                assert "system.dictionaries" in query
                assert params == {"database": "posthog"}
                return [
                    (
                        "channel_definition_dict",
                        "ClickHouse: posthog.channel_definition",
                        "ComplexKeyHashed",
                        3000,
                        3600,
                    )
                ]

        dump_dictionaries(_FakeClient(), "posthog", schema)
        t = schema["channel_definition_dict"]
        assert t.dict_source_type == "ClickHouse"
        assert t.dict_source_raw == "ClickHouse: posthog.channel_definition"
        assert t.dict_layout_type == "COMPLEXKEYHASHED"
        assert t.dict_lifetime_min == 3000
        assert t.dict_lifetime_max == 3600

    def test_skips_rows_without_system_tables_entry(self):
        """Rows in system.dictionaries with no system.tables counterpart are skipped."""
        from posthog.clickhouse.migration_tools.schema_introspect import dump_dictionaries

        schema: dict = {}

        class _FakeClient:
            def execute(self, query, params):
                return [("orphan_dict", "HTTP: https://x", "Hashed", 60, 120)]

        dump_dictionaries(_FakeClient(), "posthog", schema)
        # No TableSchema was in schema, so dump_dictionaries adds nothing.
        assert schema == {}


class TestDictionaryRecreateExtended:
    """Covers the new source/layout param checks in the recreate path."""

    @_PATCH_RESOLVE
    @_PATCH_SETTING
    def test_recreate_on_source_type_change(self, _mock_setting, _mock_cluster):
        """Changing SOURCE type (CLICKHOUSE -> HTTP) triggers recreate."""
        desired = _make_desired({"channel_definition_dict": _dict_table()})
        current = {
            "channel_definition_dict": TableSchema(
                name="channel_definition_dict",
                engine="Dictionary",
                engine_full=(
                    "Dictionary PRIMARY KEY domain, kind "
                    "SOURCE(HTTP(url 'https://x' format 'CSVWithNames')) "
                    "LAYOUT(COMPLEX_KEY_HASHED()) LIFETIME(MIN 3000 MAX 3600)"
                ),
                dict_source_type="HTTP",
                dict_layout_type="COMPLEX_KEY_HASHED",
                dict_lifetime_min=3000,
                dict_lifetime_max=3600,
                columns=[
                    _live_col("domain", "String"),
                    _live_col("kind", "String"),
                    _live_col("domain_type", "Nullable(String)"),
                ],
            )
        }
        diffs = diff_state(desired, current, database="posthog", cluster="test_cluster")
        recreates = [d for d in diffs if d.action == "recreate"]
        assert len(recreates) == 1
        assert "SOURCE type changed" in recreates[0].detail

    @_PATCH_RESOLVE
    @_PATCH_SETTING
    def test_recreate_on_source_param_change(self, _mock_setting, _mock_cluster):
        """Changing a SOURCE param (e.g. table) triggers recreate via substring match."""
        desired = _make_desired({"channel_definition_dict": _dict_table()})
        current = {
            "channel_definition_dict": TableSchema(
                name="channel_definition_dict",
                engine="Dictionary",
                engine_full=(
                    "Dictionary PRIMARY KEY domain, kind "
                    "SOURCE(CLICKHOUSE(TABLE 'old_table' PASSWORD 'secret')) "
                    "LAYOUT(COMPLEX_KEY_HASHED()) LIFETIME(MIN 3000 MAX 3600)"
                ),
                dict_source_type="ClickHouse",
                dict_layout_type="COMPLEX_KEY_HASHED",
                dict_lifetime_min=3000,
                dict_lifetime_max=3600,
                columns=[
                    _live_col("domain", "String"),
                    _live_col("kind", "String"),
                    _live_col("domain_type", "Nullable(String)"),
                ],
            )
        }
        diffs = diff_state(desired, current, database="posthog", cluster="test_cluster")
        recreates = [d for d in diffs if d.action == "recreate"]
        assert len(recreates) == 1
        assert "SOURCE param 'table'" in recreates[0].detail

    @_PATCH_RESOLVE
    @_PATCH_SETTING
    def test_recreate_on_layout_param_change(self, _mock_setting, _mock_cluster):
        """Changing LAYOUT params (e.g. PREALLOCATE) triggers recreate."""
        desired_table = _dict_table()
        desired_table.dict_layout = {"type": "COMPLEX_KEY_HASHED", "params": {"PREALLOCATE": 1}}
        desired = _make_desired({"channel_definition_dict": desired_table})
        current = {
            "channel_definition_dict": TableSchema(
                name="channel_definition_dict",
                engine="Dictionary",
                engine_full=(
                    "Dictionary PRIMARY KEY domain, kind "
                    "SOURCE(CLICKHOUSE(TABLE 'channel_definition' PASSWORD 'secret')) "
                    "LAYOUT(COMPLEX_KEY_HASHED()) LIFETIME(MIN 3000 MAX 3600)"
                ),
                dict_source_type="ClickHouse",
                dict_layout_type="COMPLEX_KEY_HASHED",
                dict_lifetime_min=3000,
                dict_lifetime_max=3600,
                columns=[
                    _live_col("domain", "String"),
                    _live_col("kind", "String"),
                    _live_col("domain_type", "Nullable(String)"),
                ],
            )
        }
        diffs = diff_state(desired, current, database="posthog", cluster="test_cluster")
        recreates = [d for d in diffs if d.action == "recreate"]
        assert len(recreates) == 1
        assert "LAYOUT param 'PREALLOCATE'" in recreates[0].detail

    @_PATCH_RESOLVE
    @_PATCH_SETTING
    def test_stable_when_source_and_layout_match(self, _mock_setting, _mock_cluster):
        """Structured fields matching desired -> 0 diffs (convergence)."""
        desired = _make_desired({"channel_definition_dict": _dict_table()})
        current = {
            "channel_definition_dict": TableSchema(
                name="channel_definition_dict",
                engine="Dictionary",
                engine_full=(
                    "Dictionary PRIMARY KEY domain, kind "
                    "SOURCE(CLICKHOUSE(TABLE 'channel_definition' PASSWORD 'secret')) "
                    "LAYOUT(COMPLEX_KEY_HASHED()) LIFETIME(MIN 3000 MAX 3600)"
                ),
                dict_source_type="ClickHouse",
                dict_layout_type="COMPLEX_KEY_HASHED",
                dict_lifetime_min=3000,
                dict_lifetime_max=3600,
                columns=[
                    _live_col("domain", "String"),
                    _live_col("kind", "String"),
                    _live_col("domain_type", "Nullable(String)"),
                ],
            )
        }
        diffs = diff_state(desired, current, database="posthog", cluster="test_cluster")
        assert len(diffs) == 0, f"Expected 0 diffs but got: {[d.detail for d in diffs]}"


class TestRenderDictRange:
    def test_renders_min_max_columns(self):
        from posthog.clickhouse.migration_tools.state_diff import _render_dict_range

        assert _render_dict_range({"min": "start_date", "max": "end_date"}) == "RANGE(MIN start_date MAX end_date)"

    def test_none_returns_empty(self):
        from posthog.clickhouse.migration_tools.state_diff import _render_dict_range

        assert _render_dict_range(None) == ""

    def test_missing_keys_raises(self):
        from posthog.clickhouse.migration_tools.state_diff import _render_dict_range

        try:
            _render_dict_range({"min": "x"})
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError")


class TestDictionaryRangeInCreateSql:
    def test_range_appears_after_lifetime(self):
        """CREATE DICTIONARY with dict_range emits RANGE(MIN x MAX y) after LIFETIME."""
        t = _dict_table()
        t.dict_layout = {"type": "RANGE_HASHED", "params": {"range_lookup_strategy": "max"}}
        t.dict_range = {"min": "start_date", "max": "end_date"}
        sql = _generate_create_sql(t, "posthog", "main")
        # RANGE must come after LIFETIME line
        assert "LIFETIME(MIN 3000 MAX 3600)" in sql
        assert "RANGE(MIN start_date MAX end_date)" in sql
        assert sql.index("RANGE") > sql.index("LIFETIME")

    def test_no_range_when_none(self):
        """CREATE DICTIONARY without dict_range emits no RANGE clause."""
        t = _dict_table()
        sql = _generate_create_sql(t, "posthog", "main")
        assert "RANGE(" not in sql

