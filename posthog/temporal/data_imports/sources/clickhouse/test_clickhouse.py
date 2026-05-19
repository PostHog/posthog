from collections.abc import AsyncIterable

import pytest
from unittest.mock import MagicMock, patch

import pyarrow as pa
from clickhouse_connect.driver.exceptions import ClickHouseError

from posthog.temporal.data_imports.sources.clickhouse.clickhouse import (
    YIELD_TARGET_ROWS,
    ClickHouseColumn,
    _build_query,
    _get_incremental_row_count,
    _has_duplicate_primary_keys,
    _parse_mv_target,
    _quote_identifier,
    _strip_type_modifiers,
    filter_clickhouse_incremental_fields,
    get_primary_keys_for_schemas,
)
from posthog.temporal.data_imports.sources.clickhouse.source import ClickHouseSource

from products.data_warehouse.backend.types import IncrementalFieldType


class TestQuoteIdentifier:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("users", "`users`"),
            ("user_id", "`user_id`"),
            ("CamelCase", "`CamelCase`"),
            ("with space", "`with space`"),
            ("with`backtick", "`with``backtick`"),
            ("123starts_with_digit", "`123starts_with_digit`"),
        ],
    )
    def test_quotes_and_escapes(self, name, expected):
        assert _quote_identifier(name) == expected

    def test_rejects_null_byte(self):
        with pytest.raises(ValueError, match="null byte"):
            _quote_identifier("bad\x00name")


class TestStripTypeModifiers:
    @pytest.mark.parametrize(
        "raw,expected_inner,expected_nullable",
        [
            ("Int64", "Int64", False),
            ("Nullable(Int64)", "Int64", True),
            ("LowCardinality(String)", "String", False),
            ("Nullable(LowCardinality(String))", "String", True),
            ("LowCardinality(Nullable(String))", "String", True),
            ("Nullable(DateTime64(6, 'UTC'))", "DateTime64(6, 'UTC')", True),
            ("Decimal(18, 4)", "Decimal(18, 4)", False),
            ("  Nullable(Int32)  ", "Int32", True),
        ],
    )
    def test_strips(self, raw, expected_inner, expected_nullable):
        inner, nullable = _strip_type_modifiers(raw)
        assert inner == expected_inner
        assert nullable is expected_nullable


class TestFilterClickHouseIncrementalFields:
    @pytest.mark.parametrize(
        "type_name,expected_type",
        [
            ("Int8", IncrementalFieldType.Integer),
            ("Int16", IncrementalFieldType.Integer),
            ("Int32", IncrementalFieldType.Integer),
            ("Int64", IncrementalFieldType.Integer),
            ("Int128", IncrementalFieldType.Integer),
            ("Int256", IncrementalFieldType.Integer),
            ("UInt8", IncrementalFieldType.Integer),
            ("UInt16", IncrementalFieldType.Integer),
            ("UInt32", IncrementalFieldType.Integer),
            ("UInt64", IncrementalFieldType.Integer),
            ("Date", IncrementalFieldType.Date),
            ("Date32", IncrementalFieldType.Date),
            ("DateTime", IncrementalFieldType.Timestamp),
            ("DateTime('UTC')", IncrementalFieldType.Timestamp),
            ("DateTime64(3)", IncrementalFieldType.Timestamp),
            ("DateTime64(6, 'UTC')", IncrementalFieldType.Timestamp),
            ("Nullable(Int64)", IncrementalFieldType.Integer),
            ("Nullable(DateTime)", IncrementalFieldType.Timestamp),
            ("LowCardinality(Int32)", IncrementalFieldType.Integer),
        ],
    )
    def test_supported_types(self, type_name, expected_type):
        result = filter_clickhouse_incremental_fields([("col", type_name, False)])
        assert result == [("col", expected_type, False)]

    @pytest.mark.parametrize(
        "type_name",
        [
            "String",
            "FixedString(8)",
            "Float32",
            "Float64",
            "Decimal(18, 4)",
            "UUID",
            "Bool",
            "Array(Int64)",
            "Map(String, Int64)",
            "Tuple(Int64, String)",
            "Enum8('a' = 1, 'b' = 2)",
            "IPv4",
            "JSON",
        ],
    )
    def test_unsupported_types_excluded(self, type_name):
        result = filter_clickhouse_incremental_fields([("col", type_name, False)])
        assert result == []

    def test_preserves_nullable_flag(self):
        result = filter_clickhouse_incremental_fields([("col", "Nullable(Int64)", True)])
        assert result == [("col", IncrementalFieldType.Integer, True)]

    def test_multiple_columns(self):
        columns = [
            ("id", "UInt64", False),
            ("name", "String", False),
            ("created_at", "DateTime64(6, 'UTC')", True),
            ("amount", "Decimal(18, 4)", False),
            ("event_date", "Date", False),
        ]
        result = filter_clickhouse_incremental_fields(columns)
        assert result == [
            ("id", IncrementalFieldType.Integer, False),
            ("created_at", IncrementalFieldType.Timestamp, True),
            ("event_date", IncrementalFieldType.Date, False),
        ]


class TestBuildQuery:
    @staticmethod
    def _cols(*specs: tuple[str, str]) -> list[ClickHouseColumn]:
        return [ClickHouseColumn(name=n, data_type=t, nullable=False) for n, t in specs]

    def test_full_refresh(self):
        query = _build_query(
            database="default",
            table_name="events",
            columns=self._cols(("id", "Int64"), ("name", "String")),
            should_use_incremental_field=False,
            incremental_field=None,
        )
        assert query == "SELECT `id`, `name` FROM `default`.`events`"

    def test_incremental(self):
        query = _build_query(
            database="default",
            table_name="events",
            columns=self._cols(("id", "Int64"), ("created_at", "DateTime64(6)")),
            should_use_incremental_field=True,
            incremental_field="created_at",
        )
        assert "SELECT `id`, `created_at` FROM `default`.`events`" in query
        assert "WHERE `created_at` > %(last_value)s" in query
        assert "ORDER BY `created_at` ASC" in query

    def test_incremental_quotes_field_with_special_chars(self):
        query = _build_query(
            database="my-db",
            table_name="weird table",
            columns=self._cols(("event time", "DateTime")),
            should_use_incremental_field=True,
            incremental_field="event time",
        )
        assert "`my-db`.`weird table`" in query
        assert "`event time`" in query

    def test_incremental_raises_without_field(self):
        with pytest.raises(ValueError, match="incremental_field can't be None"):
            _build_query(
                database="default",
                table_name="events",
                columns=self._cols(("id", "Int64")),
                should_use_incremental_field=True,
                incremental_field=None,
            )

    def test_wraps_arrow_unsupported_types_in_to_string(self):
        query = _build_query(
            database="default",
            table_name="events",
            columns=[
                ClickHouseColumn(name="id", data_type="Int64", nullable=False),
                ClickHouseColumn(name="user_id", data_type="UUID", nullable=False),
                ClickHouseColumn(name="ip", data_type="Nullable(IPv4)", nullable=True),
                ClickHouseColumn(name="tags", data_type="Array(String)", nullable=False),
                ClickHouseColumn(name="status", data_type="LowCardinality(Enum8('a' = 1))", nullable=False),
            ],
            should_use_incremental_field=False,
            incremental_field=None,
        )
        assert "`id`" in query
        assert "toString(`user_id`) AS `user_id`" in query
        assert "toString(`ip`) AS `ip`" in query
        assert "toString(`tags`) AS `tags`" in query
        assert "toString(`status`) AS `status`" in query


class TestParseMvTarget:
    def test_qualified_target(self):
        q = "CREATE MATERIALIZED VIEW default.mv TO other_db.target_tbl AS SELECT * FROM default.src"
        assert _parse_mv_target(q) == ("other_db", "target_tbl")

    def test_backticked_target(self):
        q = "CREATE MATERIALIZED VIEW default.mv TO `weird db`.`weird.tbl` AS SELECT 1"
        assert _parse_mv_target(q) == ("weird db", "weird.tbl")

    def test_unqualified_target(self):
        q = "CREATE MATERIALIZED VIEW default.mv TO target AS SELECT 1"
        assert _parse_mv_target(q) == ("", "target")

    def test_no_target(self):
        q = "CREATE MATERIALIZED VIEW default.mv (a UInt64) ENGINE = MergeTree ORDER BY a AS SELECT a FROM src"
        assert _parse_mv_target(q) is None

    def test_empty(self):
        assert _parse_mv_target(None) is None
        assert _parse_mv_target("") is None


class TestGetClickhouseRowCount:
    def _mock_client(self, query_side_effect):
        client = MagicMock()
        client.query.side_effect = query_side_effect
        return client

    def _result(self, rows):
        r = MagicMock()
        r.result_rows = rows
        return r

    def _run(self, responses):
        """responses: list of (expected_substring_in_query_or_None, result_rows)."""
        from posthog.temporal.data_imports.sources.clickhouse import clickhouse as ch_module

        calls = list(responses)

        def side_effect(query, **_kwargs):
            _, rows = calls.pop(0)
            if isinstance(rows, Exception):
                raise rows
            return self._result(rows)

        client = MagicMock()
        client.query.side_effect = side_effect

        with patch.object(ch_module, "_get_client", return_value=client):
            return ch_module.get_clickhouse_row_count(
                host="h",
                port=1,
                database="default",
                user="u",
                password="p",
                secure=True,
                verify=True,
                names=None,
            )

    def test_mergetree_uses_total_rows(self):
        counts = self._run(
            [
                (None, [("events", 100, "MergeTree", "u1", "CREATE ...")]),
            ]
        )
        assert counts == {"events": 100}

    def test_distributed_falls_back_to_count(self):
        counts = self._run(
            [
                (None, [("dist_events", None, "Distributed", "u1", "CREATE ...")]),
                (None, [(42_000,)]),
            ]
        )
        assert counts == {"dist_events": 42_000}

    def test_mv_with_to_target_resolves_target(self):
        counts = self._run(
            [
                (
                    None,
                    [
                        (
                            "events_mv",
                            None,
                            "MaterializedView",
                            "u1",
                            "CREATE MATERIALIZED VIEW default.events_mv TO default.events_target AS SELECT * FROM src",
                        )
                    ],
                ),
                (None, [("default", "events_target", 999)]),
            ]
        )
        assert counts == {"events_mv": 999}

    def test_mv_without_to_uses_inner_id(self):
        counts = self._run(
            [
                (
                    None,
                    [
                        (
                            "mv",
                            None,
                            "MaterializedView",
                            "abc-uuid",
                            "CREATE MATERIALIZED VIEW default.mv (a UInt64) ENGINE = MergeTree ORDER BY a AS SELECT a FROM src",
                        )
                    ],
                ),
                (None, [(".inner_id.abc-uuid", 55)]),
            ]
        )
        assert counts == {"mv": 55}

    def test_plain_view_skipped(self):
        counts = self._run(
            [
                (None, [("v", None, "View", "u1", "CREATE VIEW ...")]),
            ]
        )
        assert counts == {}


class TestGetPrimaryKeysForSchemas:
    def _mock_client_returning(self, per_table_rows: dict[str, list[tuple]]):
        """MagicMock client whose `query` returns sorting-key rows based on the
        `table` parameter passed to `_get_primary_keys`."""
        client = MagicMock()

        def side_effect(query, parameters=None, **_kwargs):
            table = str((parameters or {}).get("table", ""))
            result = MagicMock()
            result.result_rows = per_table_rows.get(table, [])
            return result

        client.query.side_effect = side_effect
        return client

    def _run(self, client, table_names):
        from posthog.temporal.data_imports.sources.clickhouse import clickhouse as ch_module

        with patch.object(ch_module, "_get_client", return_value=client):
            return get_primary_keys_for_schemas(
                host="h",
                port=1,
                database="default",
                user="u",
                password="p",
                secure=True,
                verify=True,
                table_names=table_names,
            )

    def test_returns_keys_per_table(self):
        client = self._mock_client_returning(
            {
                "events": [("timestamp",), ("id",)],
                "users": [("id",)],
                "logs": [],  # no sorting key
            }
        )
        result = self._run(client, ["events", "users", "logs"])
        assert result == {"events": ["timestamp", "id"], "users": ["id"], "logs": None}

    def test_empty_input(self):
        client = MagicMock()
        assert self._run(client, []) == {}
        client.query.assert_not_called()

    def test_continues_past_per_table_error(self):
        client = MagicMock()

        calls = {"n": 0}

        def side_effect(query, parameters=None, **_kwargs):
            calls["n"] += 1
            if parameters["table"] == "broken":
                raise ClickHouseError("boom")
            r = MagicMock()
            r.result_rows = [("id",)]
            return r

        client.query.side_effect = side_effect
        result = self._run(client, ["good", "broken", "other"])
        assert result["good"] == ["id"]
        assert result["broken"] is None
        assert result["other"] == ["id"]


class TestClickHouseColumnToArrowField:
    @pytest.mark.parametrize(
        "data_type,expected_arrow_type",
        [
            ("Int8", pa.int8()),
            ("Int16", pa.int16()),
            ("Int32", pa.int32()),
            ("Int64", pa.int64()),
            ("UInt8", pa.uint8()),
            ("UInt16", pa.uint16()),
            ("UInt32", pa.uint32()),
            ("UInt64", pa.uint64()),
            ("Float32", pa.float32()),
            ("Float64", pa.float64()),
            ("Bool", pa.bool_()),
            ("String", pa.string()),
            ("UUID", pa.string()),
            ("Date", pa.date32()),
            ("Date32", pa.date32()),
            ("IPv4", pa.string()),
            ("IPv6", pa.string()),
            ("Int128", pa.string()),
            ("Int256", pa.string()),
            ("UInt128", pa.string()),
            ("UInt256", pa.string()),
            ("FixedString(16)", pa.string()),
            ("Enum8('a' = 1, 'b' = 2)", pa.string()),
            ("Enum16('long_label' = 1)", pa.string()),
            ("Array(Int64)", pa.string()),
            ("Map(String, Int64)", pa.string()),
            ("Tuple(Int64, String)", pa.string()),
            ("JSON", pa.string()),
        ],
    )
    def test_simple_type_mappings(self, data_type, expected_arrow_type):
        col = ClickHouseColumn("test_col", data_type, nullable=True)
        field = col.to_arrow_field()
        assert field.type == expected_arrow_type
        assert field.name == "test_col"
        assert field.nullable is True

    def test_datetime_no_tz(self):
        col = ClickHouseColumn("ts", "DateTime", nullable=False)
        field = col.to_arrow_field()
        assert field.type == pa.timestamp("s")

    def test_datetime_with_tz(self):
        col = ClickHouseColumn("ts", "DateTime('UTC')", nullable=False)
        field = col.to_arrow_field()
        assert field.type == pa.timestamp("s", tz="UTC")

    @pytest.mark.parametrize(
        "data_type,expected_unit",
        [
            ("DateTime64(0)", "s"),
            ("DateTime64(3)", "ms"),
            ("DateTime64(6)", "us"),
            ("DateTime64(9)", "ns"),
        ],
    )
    def test_datetime64_precision(self, data_type, expected_unit):
        col = ClickHouseColumn("ts", data_type, nullable=False)
        field = col.to_arrow_field()
        assert field.type == pa.timestamp(expected_unit)

    def test_datetime64_with_tz(self):
        col = ClickHouseColumn("ts", "DateTime64(6, 'America/New_York')", nullable=False)
        field = col.to_arrow_field()
        assert field.type == pa.timestamp("us", tz="America/New_York")

    @pytest.mark.parametrize(
        "data_type,expected_precision,expected_scale",
        [
            ("Decimal(10, 2)", 10, 2),
            ("Decimal(18)", 18, 0),
            # DecimalN(S): N fixes precision (9/18/38/76), lone arg is scale.
            ("Decimal32(4)", 9, 4),
            ("Decimal64(8)", 18, 8),
            ("Decimal128(20)", 38, 20),
            ("Decimal256(40)", 76, 40),
        ],
    )
    def test_decimal_types(self, data_type, expected_precision, expected_scale):
        col = ClickHouseColumn("amt", data_type, nullable=False)
        field = col.to_arrow_field()
        assert isinstance(field.type, (pa.Decimal128Type, pa.Decimal256Type))
        assert field.type.precision == expected_precision
        assert field.type.scale == expected_scale

    def test_nullable_wrapper(self):
        col = ClickHouseColumn("id", "Nullable(Int64)", nullable=True)
        field = col.to_arrow_field()
        assert field.type == pa.int64()
        assert field.nullable is True

    def test_low_cardinality_wrapper(self):
        col = ClickHouseColumn("name", "LowCardinality(String)", nullable=False)
        field = col.to_arrow_field()
        assert field.type == pa.string()
        assert field.nullable is False

    def test_nullable_low_cardinality(self):
        col = ClickHouseColumn("name", "LowCardinality(Nullable(String))", nullable=True)
        field = col.to_arrow_field()
        assert field.type == pa.string()
        assert field.nullable is True

    def test_unknown_type_maps_to_string(self):
        col = ClickHouseColumn("mystery", "AggregateFunction(uniq, UInt64)", nullable=True)
        field = col.to_arrow_field()
        assert field.type == pa.string()


class TestClickHouseSourceNonRetryableErrors:
    @pytest.fixture
    def source(self):
        return ClickHouseSource()

    @pytest.mark.parametrize(
        "error_msg",
        [
            "Code: 516. DB::Exception: default: Authentication failed",
            "Code: 81. DB::Exception: Database `does_not_exist` doesn't exist",
            "Code: 60. DB::Exception: Table default.foo doesn't exist",
            "Could not resolve the ClickHouse host",
            "Connection refused",
            "certificate verify failed",
        ],
    )
    def test_permanent_errors_are_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable)
        assert is_non_retryable, f"Permanent error should be non-retryable: {error_msg}"

    @pytest.mark.parametrize(
        "error_msg",
        [
            "Code: 159. DB::Exception: Timeout exceeded",  # query timeout — could be retried
            "Code: 999. DB::Exception: Keeper exception",  # transient zookeeper-style errors
            "Code: 209. DB::Exception: Socket timeout",
        ],
    )
    def test_transient_errors_are_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable)
        assert not is_non_retryable, f"Transient error should be retryable: {error_msg}"


class TestTranslateError:
    def test_matches_substring_inside_long_error(self):
        msg = "Code: 516. DB::Exception: Authentication failed for user 'default'"
        assert ClickHouseSource._translate_error(msg) == "Invalid user or password"

    def test_returns_none_for_unrecognised_error(self):
        assert ClickHouseSource._translate_error("Some random error") is None


class TestGetSchemas:
    """Tests `get_schemas` with a fully mocked ClickHouse client."""

    def _make_mock_client(self, rows):
        client = MagicMock()
        result = MagicMock()
        result.result_rows = rows
        client.query.return_value = result
        return client

    def test_groups_columns_by_table(self):
        from posthog.temporal.data_imports.sources.clickhouse import clickhouse as ch_module

        rows = [
            ("events", "id", "UInt64"),
            ("events", "created_at", "DateTime64(6, 'UTC')"),
            ("events", "name", "Nullable(String)"),
            ("users", "id", "UInt64"),
            ("users", "email", "String"),
        ]
        mock_client = self._make_mock_client(rows)

        with patch.object(ch_module, "_get_client", return_value=mock_client):
            schemas = ch_module.get_schemas(
                host="localhost",
                port=8443,
                database="default",
                user="default",
                password="",
                secure=True,
                verify=True,
            )

        assert set(schemas.keys()) == {"events", "users"}
        assert len(schemas["events"]) == 3
        # Nullable detection
        events_cols = {c[0]: (c[1], c[2]) for c in schemas["events"]}
        assert events_cols["id"] == ("UInt64", False)
        assert events_cols["name"] == ("Nullable(String)", True)


class TestSourceClassValidateCredentials:
    """High-level checks on validate_credentials error mapping."""

    def test_returns_error_when_clickhouse_connection_fails(self):
        from posthog.temporal.data_imports.sources.clickhouse import source as source_module
        from posthog.temporal.data_imports.sources.clickhouse.clickhouse import ClickHouseConnectionError

        source = source_module.ClickHouseSource()

        config = MagicMock()
        config.host = "play.clickhouse.com"
        config.ssh_tunnel = None

        with patch.object(source, "ssh_tunnel_is_valid", return_value=(True, None)):
            with patch.object(source, "is_database_host_valid", return_value=(True, None)):
                with patch.object(
                    source,
                    "get_schemas",
                    side_effect=ClickHouseConnectionError("Code: 516. Authentication failed"),
                ):
                    valid, msg = source.validate_credentials(config, team_id=1)

        assert valid is False
        assert msg == "Invalid user or password"

    def test_returns_generic_message_for_unknown_error(self):
        from posthog.temporal.data_imports.sources.clickhouse import source as source_module
        from posthog.temporal.data_imports.sources.clickhouse.clickhouse import ClickHouseConnectionError

        source = source_module.ClickHouseSource()

        config = MagicMock()
        config.host = "play.clickhouse.com"
        config.ssh_tunnel = None

        with patch.object(source, "ssh_tunnel_is_valid", return_value=(True, None)):
            with patch.object(source, "is_database_host_valid", return_value=(True, None)):
                with patch.object(
                    source,
                    "get_schemas",
                    side_effect=ClickHouseConnectionError("something weird happened"),
                ):
                    valid, msg = source.validate_credentials(config, team_id=1)

        assert valid is False
        assert msg == "Could not connect to ClickHouse. Please check all connection details are valid."


class TestHasDuplicatePrimaryKeys:
    def _logger(self):
        return MagicMock()

    def test_returns_false_when_no_primary_keys(self):
        client = MagicMock()
        assert _has_duplicate_primary_keys(client, "db", "t", None, self._logger()) is False
        assert _has_duplicate_primary_keys(client, "db", "t", [], self._logger()) is False
        client.query.assert_not_called()

    def test_fails_safe_to_true_on_clickhouse_error(self):
        client = MagicMock()
        client.query.side_effect = ClickHouseError("Code: 241. Memory limit exceeded")
        # On error we must assume duplicates exist so the incremental merge is
        # blocked. Returning False here would silently corrupt the Delta table.
        assert _has_duplicate_primary_keys(client, "db", "t", ["id"], self._logger()) is True

    def test_passes_bounded_settings(self):
        client = MagicMock()
        result = MagicMock()
        result.result_rows = []
        client.query.return_value = result

        _has_duplicate_primary_keys(client, "db", "t", ["id", "ts"], self._logger())

        _, kwargs = client.query.call_args
        settings = kwargs["settings"]
        assert settings["optimize_aggregation_in_order"] == 1
        # Bounded-prefix probe: read at most 10M rows, truncate silently
        # instead of throwing. Keeps the check O(budget) regardless of
        # table size.
        assert settings["max_rows_to_read"] == 10_000_000
        assert settings["read_overflow_mode"] == "break"
        assert settings["max_execution_time"] == 30
        assert settings["max_memory_usage"] == 1_000_000_000


class TestGetIncrementalRowCount:
    def _logger(self):
        return MagicMock()

    def test_returns_count_from_query(self):
        client = MagicMock()
        result = MagicMock()
        result.result_rows = [(42,)]
        client.query.return_value = result

        count = _get_incremental_row_count(client, "db", "t", "created_at", "2024-01-01", self._logger())
        assert count == 42

        args, kwargs = client.query.call_args
        assert "`created_at` > %(last_value)s" in args[0]
        assert kwargs["parameters"] == {"last_value": "2024-01-01"}
        assert kwargs["settings"] == {"max_execution_time": 30}

    def test_returns_none_on_error(self):
        client = MagicMock()
        client.query.side_effect = ClickHouseError("timeout")
        assert _get_incremental_row_count(client, "db", "t", "id", 0, self._logger()) is None

    def test_returns_none_when_count_is_null(self):
        client = MagicMock()
        result = MagicMock()
        result.result_rows = [(None,)]
        client.query.return_value = result
        assert _get_incremental_row_count(client, "db", "t", "id", 0, self._logger()) is None


class TestGetRowsBatching:
    """The source accumulates small Arrow blocks into larger pa.Tables before
    yielding so Delta gets fewer, larger commits. Verify the accumulation
    boundaries."""

    def _stream_context(self, blocks):
        """Build a fake `query_arrow_stream(...)` that returns `blocks`."""
        cm = MagicMock()
        cm.__enter__.return_value = iter(blocks)
        cm.__exit__.return_value = False
        return cm

    def _run_get_rows(self, blocks):
        """Invoke `clickhouse_source(...).items()` against a stream of `blocks`."""
        from contextlib import contextmanager

        from posthog.temporal.data_imports.sources.clickhouse import clickhouse as ch_module

        # Minimal discovery stubs so clickhouse_source builds a SourceResponse.
        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_table.to_arrow_schema.return_value = pa.schema([pa.field("id", pa.int64())])

        stream_client = MagicMock()
        stream_client.query_arrow_stream.return_value = self._stream_context(blocks)

        @contextmanager
        def fake_tunnel():
            yield ("localhost", 8443)

        clients = [mock_client, stream_client]

        def fake_get_client(**_kwargs):
            return clients.pop(0)

        with (
            patch.object(ch_module, "_get_client", side_effect=fake_get_client),
            patch.object(ch_module, "_get_table", return_value=mock_table),
            patch.object(ch_module, "_get_primary_keys", return_value=["id"]),
            patch.object(ch_module, "_has_duplicate_primary_keys", return_value=False),
            patch.object(ch_module, "_get_partition_settings", return_value=None),
            patch.object(ch_module, "get_clickhouse_row_count", return_value={}),
        ):
            response = ch_module.clickhouse_source(
                tunnel=fake_tunnel,
                user="u",
                password="p",
                database="db",
                secure=True,
                verify=True,
                table_names=["events"],
                should_use_incremental_field=False,
                logger=MagicMock(),
                db_incremental_field_last_value=None,
            )
            items = response.items()
            assert not isinstance(items, AsyncIterable)
            return list(items)

    def _block(self, rows):
        return pa.RecordBatch.from_arrays([pa.array(list(range(rows)), type=pa.int64())], names=["id"])

    def test_accumulates_until_row_target(self):
        # 5 blocks × 30k rows = 150k total > YIELD_TARGET_ROWS (100k).
        # Expect 2 yielded tables: one at/after 100k rows, one with the rest.
        blocks = [self._block(30_000) for _ in range(5)]
        yielded = self._run_get_rows(blocks)
        assert len(yielded) == 2
        assert sum(t.num_rows for t in yielded) == 150_000
        # First yield must have crossed the row target.
        assert yielded[0].num_rows >= YIELD_TARGET_ROWS

    def test_single_batch_below_target(self):
        # Small blocks below row/byte targets must still flush on stream end.
        blocks = [self._block(100), self._block(200)]
        yielded = self._run_get_rows(blocks)
        assert len(yielded) == 1
        assert yielded[0].num_rows == 300

    def test_skips_empty_blocks(self):
        blocks = [self._block(0), self._block(50), self._block(0)]
        yielded = self._run_get_rows(blocks)
        assert len(yielded) == 1
        assert yielded[0].num_rows == 50

    def test_empty_stream_yields_nothing(self):
        assert self._run_get_rows([]) == []
