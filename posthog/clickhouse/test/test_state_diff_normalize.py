"""Tests for state_diff normalization helpers — pure functions, no diff_state calls."""

from unittest.mock import patch

from posthog.clickhouse.migration_tools.state_diff import (
    _is_kafka_virtual_column,
    _normalize_default,
    _normalize_interval_funcs,
    _normalize_mv_select,
    _normalize_type,
    _render_dict_layout,
    _render_dict_lifetime,
    _render_dict_source,
    _strip_redundant_parens,
)


class TestNormalizeIntervalFuncs:
    def test_toIntervalDay(self):
        assert _normalize_interval_funcs("today() + toIntervalDay(7)") == "today() + INTERVAL 7 DAY"

    def test_toIntervalHour(self):
        assert _normalize_interval_funcs("now() + toIntervalHour(24)") == "now() + INTERVAL 24 HOUR"

    def test_toIntervalMinute(self):
        assert _normalize_interval_funcs("toIntervalMinute(30)") == "INTERVAL 30 MINUTE"

    def test_no_change_for_interval_literal(self):
        s = "INTERVAL 7 DAY"
        assert _normalize_interval_funcs(s) == s

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

    def test_lambda_parens_stripped(self):
        a = "mapFilter((key, _) -> (key NOT LIKE '$%'), m)"
        b = "mapFilter((key, _) -> key NOT LIKE '$%', m)"
        assert _normalize_default(a) == _normalize_default(b)

    def test_nested_lambda_triple_and(self):
        ch = "DEFAULT mapFilter((k, v) -> ((k LIKE 'a%') AND (k NOT LIKE 'b%') AND (v != '')), m)"
        yaml = "DEFAULT mapFilter((k, v) -> k LIKE 'a%' AND k NOT LIKE 'b%' AND v != '', m)"
        assert _normalize_default(ch) == _normalize_default(yaml)


class TestKafkaVirtualColumns:
    def test_known_virtual_columns(self):
        for col in ("_topic", "_key", "_offset", "_partition", "_timestamp", "_headers"):
            assert _is_kafka_virtual_column(col), f"{col} should be virtual"

    def test_headers_dot_prefix(self):
        assert _is_kafka_virtual_column("_headers.name")

    def test_regular_column_not_virtual(self):
        assert not _is_kafka_virtual_column("team_id")


class TestNormalizeType:
    def test_enum8_to_enum(self):
        assert _normalize_type("Enum8('a' = 1, 'button' = 2)") == "Enum('a', 'button')"

    def test_enum16_to_enum(self):
        assert _normalize_type("Enum16('x' = 100, 'y' = 200)") == "Enum('x', 'y')"

    def test_array_enum8(self):
        assert _normalize_type("Array(Enum8('a' = 1, 'button' = 2))") == "Array(Enum('a', 'button'))"

    def test_datetime64_default_precision(self):
        assert _normalize_type("DateTime64") == "DateTime64(3)"

    def test_datetime64_explicit_3(self):
        assert _normalize_type("DateTime64(3)") == "DateTime64(3)"

    def test_nullable_datetime64(self):
        assert _normalize_type("Nullable(DateTime64)") == "Nullable(DateTime64(3))"

    def test_decimal_18_10_to_decimal64(self):
        assert _normalize_type("Decimal(18, 10)") == "Decimal64(10)"

    def test_decimal_9_2_to_decimal32(self):
        assert _normalize_type("Decimal(9, 2)") == "Decimal32(2)"

    def test_non_enum_unchanged(self):
        assert _normalize_type("String") == "String"


class TestStripRedundantParens:
    def test_outer_lambda_parens(self):
        assert _strip_redundant_parens("-> (x + 1)") == "-> x + 1"

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


class TestNormalizeMvSelect:
    def test_database_prefix_stripped(self):
        ch = "SELECT event FROM posthog_test.kafka_events"
        yaml = "SELECT event FROM kafka_events"
        assert _normalize_mv_select(ch, database="posthog_test") == _normalize_mv_select(yaml, database="posthog_test")

    def test_keyword_case_normalized(self):
        ch = "SELECT event FROM kafka_events WHERE team_id = 1"
        yaml = "select event from kafka_events where team_id = 1"
        assert _normalize_mv_select(ch) == _normalize_mv_select(yaml)

    def test_trailing_settings_stripped(self):
        ch = "SELECT event FROM kafka_events SETTINGS max_threads = 4"
        yaml = "SELECT event FROM kafka_events"
        assert _normalize_mv_select(ch) == _normalize_mv_select(yaml)

    def test_join_aliases_preserved(self):
        """``a.col``/``b.col`` in JOIN must not be stripped — they are table aliases, not DB prefixes."""
        sql = "SELECT a.x, b.y FROM t1 AS a JOIN t2 AS b ON a.id = b.id"
        out = _normalize_mv_select(sql, database="posthog")
        assert "a.x" in out and "b.y" in out

    def test_settings_inside_subquery_preserved(self):
        """Trailing SETTINGS strip must not chop a subquery's SETTINGS clause."""
        sql = "SELECT x FROM (SELECT y FROM t SETTINGS max_threads = 4) z SETTINGS insert_quorum = 2"
        out = _normalize_mv_select(sql)
        assert "insert_quorum" not in out, "outer SETTINGS should be stripped"
        assert "max_threads" in out, "subquery SETTINGS must survive"


class TestRenderDictSource:
    def test_clickhouse_source(self):
        s = _render_dict_source({"type": "CLICKHOUSE", "table": "channel_definition", "password": "secret"})
        assert s == "SOURCE(CLICKHOUSE(table 'channel_definition' password 'secret'))"

    def test_from_settings_sentinel_resolves(self):
        with patch(
            "posthog.clickhouse.migration_tools.state_diff._resolve_setting",
            side_effect=lambda k: f"RESOLVED_{k}",
        ):
            s = _render_dict_source({"type": "CLICKHOUSE", "table": "x", "password": "__from_settings__"})
        assert "password 'RESOLVED_password'" in s

    def test_settings_resolution_keys_match_yaml_param_names(self):
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
