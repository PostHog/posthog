"""Tests for the table-driven Postgres to ClickHouse ETL pipeline."""

import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from django.contrib.postgres.fields import ArrayField
from django.db.models import JSONField, Model

from dagster import build_asset_context, build_op_context
from parameterized import parameterized

from posthog.dags.postgres_to_clickhouse_etl import (
    TABLE_CONFIGS,
    IncrementalState,
    PostgresToClickHouseETLConfig,
    TableConfig,
    _sync_table,
    create_clickhouse_tables,
    feature_flags_in_clickhouse,
    fetch_rows_in_batches,
    insert_rows_to_clickhouse,
    organizations_in_clickhouse,
    postgres_to_clickhouse_etl_job,
    postgres_to_clickhouse_hourly_schedule,
    teams_in_clickhouse,
    transform_row,
    verify_sync,
)
from posthog.models import Organization, Team

from products.feature_flags.backend.models.feature_flag import FeatureFlag

_MIRRORED_TABLES = [
    ("posthog_organization", Organization),
    ("posthog_team", Team),
    ("posthog_featureflag", FeatureFlag),
]


def _fields_by_column(model: type[Model]) -> dict[str, Any]:
    fields_by_column: dict[str, Any] = {}
    for model_field in model._meta.get_fields():
        column = getattr(model_field, "column", None)
        if column:
            fields_by_column[column] = model_field
    return fields_by_column


def _composite_columns(cfg: TableConfig, model: type[Model]) -> list[tuple[str, Any]]:
    fields_by_column = _fields_by_column(model)
    return [
        (col, fields_by_column[col])
        for col in cfg.select_columns
        if isinstance(fields_by_column.get(col), ArrayField | JSONField)
    ]


def _post_transform_serializes(table_name: str, column: str, model_field: Any) -> bool:
    # posthog_featureflag serializes `filters` inside its post_transform instead of declaring the
    # column on the config, so ask the transform what it emits rather than restating that here.
    probe = [{"probe": 1}] if isinstance(model_field, ArrayField) else {"probe": 1}
    return isinstance(transform_row(table_name, {column: probe}).get(column), str)


def _config(**overrides) -> PostgresToClickHouseETLConfig:
    base: dict = {
        "full_refresh": False,
        "batch_size": 10000,
        "backward_lookback_seconds": 86400,
    }
    base.update(overrides)
    return PostgresToClickHouseETLConfig(**base)


def _flag_row(**overrides):
    row = {
        "id": 7,
        "team_id": 42,
        "key": "new-checkout",
        "name": "New checkout flow",
        "filters": {"groups": []},
        "deleted": False,
        "active": True,
        "archived": False,
        "version": 3,
        "ensure_experience_continuity": False,
        "has_enriched_analytics": True,
        "is_remote_configuration": False,
        "has_encrypted_payloads": False,
        "evaluation_runtime": "server",
        "bucketing_identifier": "distinct_id",
        "created_by_id": 11,
        "usage_dashboard_id": None,
        "created_at": datetime(2025, 3, 1, 12, 0, 0),
        "updated_at": None,
    }
    row.update(overrides)
    return row


class TestTransformations:
    def test_transform_organization_row(self):
        import uuid

        test_uuid = uuid.uuid4()
        row = {
            "id": test_uuid,
            "name": "Test Org",
            "logo_media_id": uuid.uuid4(),
            "is_member_join_email_enabled": True,
            "is_hipaa": False,
            "available_product_features": [{"key": "feature1"}],  # ArrayField, so psycopg2 parses it
            "usage": '{"events": 1000}',  # ::text on the PG side
            "personalization": '{"role": "engineer"}',
            "domain_whitelist": ["example.com"],
        }
        usage_text = row["usage"]

        transformed = transform_row("posthog_organization", row)

        assert transformed["id"] == str(test_uuid)
        assert isinstance(transformed["logo_media_id"], str)
        assert transformed["is_member_join_email_enabled"] == 1
        assert transformed["is_hipaa"] == 0
        # ArrayField columns arrive as Python lists, but the mirror column is String, so the
        # ClickHouse driver rejects any value the transform leaves unserialized.
        assert transformed["available_product_features"] == '[{"key": "feature1"}]'
        # ::text columns pass through untouched, with no parse-then-redump.
        assert transformed["usage"] == usage_text
        assert transformed["domain_whitelist"] == ["example.com"]

    def test_transform_team_row(self):
        import uuid

        team_uuid = uuid.uuid4()
        org_uuid = uuid.uuid4()
        row = {
            "id": 1,
            "uuid": team_uuid,
            "organization_id": org_uuid,
            "name": "Test Team",
            "anonymize_ips": True,
            "session_recording_opt_in": False,
            "test_account_filters": '[{"key": "email", "value": "test@example.com"}]',
            "app_urls": ["https://app.example.com"],
            "person_display_name_properties": None,
            "session_recording_url_trigger_config": [{"url": "example.com", "matching": "regex"}],
            "session_recording_url_blocklist_config": None,
            "session_recording_event_trigger_config": ["$pageview"],
            "session_recording_sample_rate": Decimal("0.50"),
            "drop_events_older_than": timedelta(days=30),
        }
        test_account_filters_text = row["test_account_filters"]

        transformed = transform_row("posthog_team", row)

        assert transformed["uuid"] == str(team_uuid)
        assert transformed["organization_id"] == str(org_uuid)
        assert transformed["anonymize_ips"] == 1
        assert transformed["session_recording_opt_in"] == 0
        assert transformed["test_account_filters"] == test_account_filters_text
        assert transformed["app_urls"] == ["https://app.example.com"]
        assert transformed["person_display_name_properties"] == []
        # ArrayField columns arrive as Python lists, but the mirror column is String, so the
        # ClickHouse driver rejects any value the transform leaves unserialized.
        assert transformed["session_recording_url_trigger_config"] == '[{"url": "example.com", "matching": "regex"}]'
        assert transformed["session_recording_event_trigger_config"] == '["$pageview"]'
        # The mirror column is Nullable(String), so a NULL source value stays NULL.
        assert transformed["session_recording_url_blocklist_config"] is None
        assert transformed["session_recording_sample_rate"] == Decimal("0.50")
        assert transformed["drop_events_older_than"] == 30 * 24 * 60 * 60

    def test_transform_feature_flag_row_null_updated_at_coalesces_to_created_at(self):
        # updated_at is NULL until a flag's first edit; the mirror must not store NULL because the
        # watermark read depends on it.
        created = datetime(2025, 3, 1, 12, 0, 0)
        row = _flag_row(created_at=created, updated_at=None)

        transformed = transform_row("posthog_featureflag", row)

        assert transformed["updated_at"] == created

    def test_transform_feature_flag_row_serializes_filters(self):
        original_filters = {
            "groups": [{"properties": [{"key": "email", "value": "@posthog.com", "type": "person"}]}],
            "multivariate": {"variants": [{"key": "control"}, {"key": "test"}]},
        }
        row = _flag_row(filters=original_filters)

        transformed = transform_row("posthog_featureflag", row)

        # transform mutates the row in place (filters becomes a JSON string), so parse it back and compare to the original dict.
        assert json.loads(transformed["filters"]) == original_filters
        assert transformed["deleted"] == 0
        assert transformed["active"] == 1

    def test_transform_feature_flag_row_unparseable_filters_falls_back_to_empty_dict(self):
        transformed = transform_row("posthog_featureflag", _flag_row(filters="not json"))

        assert transformed["filters"] == "{}"

    def test_transform_feature_flag_row_redacts_payload_ciphertext(self):
        # Rotation commands update filters.payloads without touching updated_at, so the incremental
        # mirror never sees a rotation. Substituting ciphertext with the redaction sentinel keeps the
        # variant-key shape intact without mirroring ciphertext after a key is retired.
        from products.feature_flags.backend.encrypted_flag_payloads import REDACTED_PAYLOAD_VALUE

        row = _flag_row(
            filters={
                "groups": [],
                "payloads": {"control": "gAAAAABkp8G8_example_ciphertext", "test": "gAAAAABkp8G8_another"},
            },
            has_encrypted_payloads=True,
        )

        transformed = transform_row("posthog_featureflag", row)

        mirrored = json.loads(transformed["filters"])
        assert mirrored["payloads"] == {
            "control": REDACTED_PAYLOAD_VALUE,
            "test": REDACTED_PAYLOAD_VALUE,
        }

    def test_transform_feature_flag_row_leaves_empty_payload_dict_alone(self):
        transformed = transform_row("posthog_featureflag", _flag_row(filters={"groups": [], "payloads": {}}))

        mirrored = json.loads(transformed["filters"])
        assert mirrored["payloads"] == {}

    def test_transform_row_unknown_table_raises(self):
        with pytest.raises(KeyError):
            transform_row("posthog_nonexistent", {})


class TestConfigCoversPostgresCompositeTypes:
    # Every mirrored column that psycopg2 hands over as a Python list or dict must be adapted before
    # the insert, either by a TableConfig field list or by the table's post_transform. Without an
    # adaptation the value reaches a ClickHouse String column unserialized and the driver raises
    # AttributeError instead of inserting.
    @parameterized.expand(_MIRRORED_TABLES)
    def test_every_array_and_json_column_has_an_adaptation(self, table_name, model):
        cfg = TABLE_CONFIGS[table_name]
        declared = set(cfg.jsonb_text_cast) | set(cfg.array_fields) | set(cfg.json_dumps_fields)

        unhandled = [
            col
            for col, model_field in _composite_columns(cfg, model)
            if col not in declared and not _post_transform_serializes(table_name, col, model_field)
        ]

        assert unhandled == []

    @parameterized.expand(_MIRRORED_TABLES)
    def test_array_columns_are_never_cast_to_text(self, table_name, model):
        # `col::text` on an ArrayField renders Postgres array literal syntax, which JSONExtract*
        # cannot read. Those columns must go through json_dumps_fields or array_fields instead.
        cfg = TABLE_CONFIGS[table_name]
        fields_by_column = _fields_by_column(model)

        miscast = [col for col in cfg.jsonb_text_cast if isinstance(fields_by_column.get(col), ArrayField)]

        assert miscast == []


class TestTableDdl:
    def test_organization_ddl(self):
        sql = TABLE_CONFIGS["posthog_organization"].ddl()
        assert "models.posthog_organization" in sql
        assert "ReplicatedReplacingMergeTree" in sql

    def test_team_ddl(self):
        sql = TABLE_CONFIGS["posthog_team"].ddl()
        assert "models.posthog_team" in sql
        assert "ReplicatedReplacingMergeTree" in sql

    def test_feature_flag_ddl_shape(self):
        sql = TABLE_CONFIGS["posthog_featureflag"].ddl()
        assert "models.posthog_featureflag" in sql
        assert "ReplicatedReplacingMergeTree" in sql
        assert "key String" in sql
        assert "filters String" in sql
        # Identity alone, so ReplacingMergeTree collapses a flag's versions instead of keeping one
        # row per edit. id rather than key because tombstones rename key; see the TableConfig note.
        assert "ORDER BY (team_id, id)" in sql
        # updated_at as the version column, so the newest Postgres state wins even when a backfill
        # re-inserts an older window after the hourly sync.
        assert "'{shard}-{replica}', updated_at)" in sql


class TestFetchRowsInBatches:
    def _conn_yielding(self, batches):
        mock_cursor = MagicMock()
        mock_cursor.fetchmany.side_effect = [*batches, []]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        return mock_conn, mock_cursor

    def test_no_incremental_filter_for_full_refresh(self):
        conn, cursor = self._conn_yielding([[{"id": 1}]])
        list(fetch_rows_in_batches(conn, "posthog_organization", None, batch_size=100))

        sql = cursor.execute.call_args[0][0]
        assert "FROM posthog_organization" in sql
        assert "WHERE" not in sql

    def test_incremental_filter_uses_watermark_column(self):
        conn, cursor = self._conn_yielding([[{"id": 1}]])
        list(fetch_rows_in_batches(conn, "posthog_organization", datetime(2024, 1, 1), batch_size=100))

        sql, params = cursor.execute.call_args[0]
        assert "WHERE updated_at > %s" in sql
        assert params == [datetime(2024, 1, 1)]

    def test_feature_flag_incremental_catches_updated_and_created_rows(self):
        # A flag's first edit sets updated_at; creation sets created_at and leaves updated_at NULL.
        # The COALESCE watermark must pick up either one moving into the window.
        conn, cursor = self._conn_yielding([[{"id": 1}]])
        list(fetch_rows_in_batches(conn, "posthog_featureflag", datetime(2024, 1, 1), batch_size=100))

        sql, params = cursor.execute.call_args[0]
        assert "WHERE COALESCE(updated_at, created_at) > %s" in sql
        assert "ORDER BY COALESCE(updated_at, created_at) ASC" in sql
        assert params == [datetime(2024, 1, 1)]

    def test_jsonb_columns_selected_as_text_to_skip_parse(self):
        """Org/team JSON columns go over the wire as text so psycopg2 doesn't parse them only to re-serialize."""
        conn, cursor = self._conn_yielding([[{"id": 1}]])
        list(fetch_rows_in_batches(conn, "posthog_team", None, batch_size=100))

        sql = cursor.execute.call_args[0][0]
        assert "test_account_filters::text AS test_account_filters" in sql

    def test_flag_filters_not_cast_to_text(self):
        conn, cursor = self._conn_yielding([[{"id": 1}]])
        list(fetch_rows_in_batches(conn, "posthog_featureflag", None, batch_size=100))

        sql = cursor.execute.call_args[0][0]
        assert "filters::text" not in sql
        assert " filters" in sql

    def test_named_server_side_cursor_used(self):
        conn, _ = self._conn_yielding([[{"id": 1}]])
        list(fetch_rows_in_batches(conn, "posthog_organization", None, batch_size=100))
        assert conn.cursor.call_args[1].get("name") is not None


def _org_row(**overrides):
    """A full org row, as the SELECT always returns every configured column."""
    row = dict.fromkeys(TABLE_CONFIGS["posthog_organization"].select_columns)
    row.update(
        {
            "id": 1,
            "name": "Org",
            "is_member_join_email_enabled": True,
            "available_product_features": [],
            "created_at": datetime(2024, 1, 1),
            "updated_at": datetime(2024, 1, 2),
        }
    )
    row.update(overrides)
    return row


class TestInsertRowsToClickHouse:
    @patch("posthog.dags.postgres_to_clickhouse_etl.sync_execute")
    def test_empty_rows_returns_zero(self, mock_sync_execute):
        assert insert_rows_to_clickhouse("posthog_organization", [], batch_size=10) == 0
        mock_sync_execute.assert_not_called()

    @patch("posthog.dags.postgres_to_clickhouse_etl.sync_execute")
    def test_insert_targets_models_db_with_parameterized_values(self, mock_sync_execute):
        n = insert_rows_to_clickhouse("posthog_organization", [_org_row()], batch_size=10)

        assert n == 1
        call = mock_sync_execute.call_args[0]
        assert "INSERT INTO models.posthog_organization" in call[0]
        assert "VALUES" in call[0]
        # Data is passed as a separate argument, not inlined into SQL text — lets the driver's
        # columnar writer handle arrays / datetimes / strings with embedded quotes.
        assert call[1] is not None

    @patch("posthog.dags.postgres_to_clickhouse_etl.sync_execute")
    def test_insert_raises_on_missing_configured_column(self, mock_sync_execute):
        # A row missing a configured column is a bug upstream (transform drift, config typo);
        # the insert must raise naming the column, not silently write NULL into a required field.
        row = _org_row()
        del row["id"]

        with pytest.raises(KeyError, match="id"):
            insert_rows_to_clickhouse("posthog_organization", [row], batch_size=10)
        mock_sync_execute.assert_not_called()

    @patch("posthog.dags.postgres_to_clickhouse_etl.sync_execute")
    def test_insert_batches_by_batch_size(self, mock_sync_execute):
        rows = [_org_row(id=i, name=f"Org {i}") for i in range(25)]

        n = insert_rows_to_clickhouse("posthog_organization", rows, batch_size=10)

        assert n == 25
        assert mock_sync_execute.call_count == 3


class TestCreateClickHouseTables:
    @patch("posthog.dags.postgres_to_clickhouse_etl.get_cluster")
    def test_creates_database_plus_three_tables(self, mock_get_cluster):
        mock_cluster = MagicMock()
        mock_futures = MagicMock()
        mock_futures.result.return_value = {}
        mock_cluster.map_all_hosts.return_value = mock_futures
        mock_get_cluster.return_value = mock_cluster

        create_clickhouse_tables()

        assert mock_cluster.map_all_hosts.call_count == 4  # 1 DB + 3 tables
        sqls = [call[0][0].query for call in mock_cluster.map_all_hosts.call_args_list]
        assert any("CREATE DATABASE IF NOT EXISTS models" in sql for sql in sqls)
        for table in ("posthog_organization", "posthog_team", "posthog_featureflag"):
            assert any(f"models.{table}" in sql and "ReplicatedReplacingMergeTree" in sql for sql in sqls)


class TestSyncTable:
    @patch("posthog.dags.postgres_to_clickhouse_etl.sync_execute")
    @patch("posthog.dags.postgres_to_clickhouse_etl.get_postgres_connection")
    @patch("posthog.dags.postgres_to_clickhouse_etl.create_clickhouse_tables")
    def test_incremental_advances_watermark_to_latest_seen_row(
        self, mock_create_tables, mock_get_pg, mock_sync_execute
    ):
        mock_sync_execute.side_effect = [
            [[None]],  # first-run watermark read on an empty mirror
            None,  # INSERT
        ]
        mock_get_pg.return_value = MagicMock()
        with (
            patch("posthog.dags.postgres_to_clickhouse_etl.fetch_rows_in_batches") as mock_fetch,
            patch("posthog.dags.postgres_to_clickhouse_etl.insert_rows_to_clickhouse") as mock_insert,
        ):
            mock_fetch.return_value = iter(
                [[{"id": 1, "updated_at": datetime(2024, 1, 2)}, {"id": 2, "updated_at": datetime(2024, 1, 3)}]]
            )
            mock_insert.return_value = 2
            context = build_op_context()

            state = _sync_table(context, _config(backward_lookback_seconds=0), "posthog_organization")

            assert isinstance(state, IncrementalState)
            assert state.rows_synced == 2
            assert state.last_sync_timestamp == datetime(2024, 1, 3)
            mock_insert.assert_called_once()

    @patch("posthog.dags.postgres_to_clickhouse_etl.sync_execute")
    @patch("posthog.dags.postgres_to_clickhouse_etl.get_postgres_connection")
    @patch("posthog.dags.postgres_to_clickhouse_etl.create_clickhouse_tables")
    def test_incremental_watermark_wraps_back_by_lookback_window(
        self, mock_create_tables, mock_get_pg, mock_sync_execute
    ):
        """The PG query is invoked with (mirror high-watermark − backward_lookback_seconds), not the raw watermark."""
        mock_sync_execute.return_value = [[datetime(2024, 3, 10, 12, 0, 0)]]
        mock_get_pg.return_value = MagicMock()
        with (
            patch("posthog.dags.postgres_to_clickhouse_etl.fetch_rows_in_batches") as mock_fetch,
            patch("posthog.dags.postgres_to_clickhouse_etl.insert_rows_to_clickhouse"),
        ):
            mock_fetch.return_value = iter([])
            context = build_op_context()

            _sync_table(context, _config(backward_lookback_seconds=3600), "posthog_organization")

            mock_fetch.assert_called_once()
            # fetch_rows_in_batches(conn, table_name, last_sync, batch_size) — third positional arg.
            last_sync_arg = mock_fetch.call_args[0][2]
            assert last_sync_arg == datetime(2024, 3, 10, 11, 0, 0)

    @patch("posthog.dags.postgres_to_clickhouse_etl.sync_execute")
    @patch("posthog.dags.postgres_to_clickhouse_etl.get_postgres_connection")
    @patch("posthog.dags.postgres_to_clickhouse_etl.create_clickhouse_tables")
    def test_flags_use_per_table_lookback_not_job_config(self, mock_create_tables, mock_get_pg, mock_sync_execute):
        """posthog_featureflag's watermark wraps by its TableConfig lookback even when the job-level lookback is 0."""
        mock_sync_execute.return_value = [[datetime(2024, 3, 10, 12, 0, 0)]]
        mock_get_pg.return_value = MagicMock()
        with (
            patch("posthog.dags.postgres_to_clickhouse_etl.fetch_rows_in_batches") as mock_fetch,
            patch("posthog.dags.postgres_to_clickhouse_etl.insert_rows_to_clickhouse"),
        ):
            mock_fetch.return_value = iter([])
            context = build_op_context()

            _sync_table(context, _config(backward_lookback_seconds=0), "posthog_featureflag")

            last_sync_arg = mock_fetch.call_args[0][2]
            assert last_sync_arg == datetime(2024, 3, 10, 12, 0, 0) - timedelta(
                seconds=TABLE_CONFIGS["posthog_featureflag"].lookback_seconds
            )

    def test_flags_lookback_defaults_to_one_hour(self):
        """Flags re-emit one hourly cycle; orgs and teams keep the 24h outage window."""
        assert TABLE_CONFIGS["posthog_featureflag"].lookback_seconds == 3600
        assert TABLE_CONFIGS["posthog_organization"].lookback_seconds == 86400
        assert TABLE_CONFIGS["posthog_team"].lookback_seconds == 86400

    @patch("posthog.dags.postgres_to_clickhouse_etl.sync_execute")
    @patch("posthog.dags.postgres_to_clickhouse_etl.get_postgres_connection")
    @patch("posthog.dags.postgres_to_clickhouse_etl.create_clickhouse_tables")
    def test_full_refresh_truncates_table(self, mock_create_tables, mock_get_pg, mock_sync_execute):
        mock_sync_execute.return_value = None
        mock_get_pg.return_value = MagicMock()
        with (
            patch("posthog.dags.postgres_to_clickhouse_etl.fetch_rows_in_batches") as mock_fetch,
            patch("posthog.dags.postgres_to_clickhouse_etl.insert_rows_to_clickhouse"),
        ):
            mock_fetch.return_value = iter([])
            context = build_op_context()

            state = _sync_table(context, _config(full_refresh=True), "posthog_team")

            assert state.rows_synced == 0
            mock_sync_execute.assert_any_call("TRUNCATE TABLE models.posthog_team")

    @patch("posthog.dags.postgres_to_clickhouse_etl.sync_execute")
    @patch("posthog.dags.postgres_to_clickhouse_etl.get_postgres_connection")
    @patch("posthog.dags.postgres_to_clickhouse_etl.create_clickhouse_tables")
    def test_empty_postgres_result_leaves_watermark_state_empty(
        self, mock_create_tables, mock_get_pg, mock_sync_execute
    ):
        """Watermark state comes only from this run's PG rows; the stored mirror watermark is a hint, not state."""
        mock_sync_execute.return_value = [[datetime(2024, 1, 1)]]
        mock_get_pg.return_value = MagicMock()
        with (
            patch("posthog.dags.postgres_to_clickhouse_etl.fetch_rows_in_batches") as mock_fetch,
            patch("posthog.dags.postgres_to_clickhouse_etl.insert_rows_to_clickhouse"),
        ):
            mock_fetch.return_value = iter([])
            context = build_op_context()

            state = _sync_table(context, _config(), "posthog_team")

            assert state.last_sync_timestamp is None
            assert state.rows_synced == 0

    @patch("posthog.dags.postgres_to_clickhouse_etl.get_postgres_connection")
    @patch("posthog.dags.postgres_to_clickhouse_etl.create_clickhouse_tables")
    @patch("posthog.dags.postgres_to_clickhouse_etl.sync_execute")
    def test_errors_close_postgres_connection(self, mock_sync_execute, mock_create_tables, mock_get_pg):
        mock_sync_execute.return_value = [[None]]
        mock_pg = MagicMock()
        mock_get_pg.return_value = mock_pg

        with patch("posthog.dags.postgres_to_clickhouse_etl.fetch_rows_in_batches") as mock_fetch:
            mock_fetch.side_effect = Exception("connection lost")
            context = build_op_context()

            with pytest.raises(Exception, match="connection lost"):
                _sync_table(context, _config(), "posthog_organization")

            mock_pg.close.assert_called_once()

    @patch("posthog.dags.postgres_to_clickhouse_etl.sync_execute")
    @patch("posthog.dags.postgres_to_clickhouse_etl.get_postgres_connection")
    @patch("posthog.dags.postgres_to_clickhouse_etl.create_clickhouse_tables")
    def test_feature_flag_watermark_skips_null_updated_at_in_mixed_batch(
        self, mock_create_tables, mock_get_pg, mock_sync_execute
    ):
        """A batch mixing edited and never-edited flags must not crash max() and must advance to the edited flag."""
        mock_sync_execute.side_effect = [
            [[None]],
            None,
        ]
        mock_get_pg.return_value = MagicMock()
        edited_at = datetime(2025, 4, 15, 10, 0, 0)
        with (
            patch("posthog.dags.postgres_to_clickhouse_etl.fetch_rows_in_batches") as mock_fetch,
            patch("posthog.dags.postgres_to_clickhouse_etl.insert_rows_to_clickhouse") as mock_insert,
        ):
            mock_fetch.return_value = iter(
                [
                    [
                        {"id": 7, "team_id": 42, "created_at": datetime(2025, 3, 1), "updated_at": None},
                        {"id": 8, "team_id": 42, "created_at": datetime(2025, 3, 2), "updated_at": edited_at},
                    ]
                ]
            )
            mock_insert.return_value = 2
            context = build_op_context()

            state = _sync_table(context, _config(backward_lookback_seconds=0), "posthog_featureflag")

            assert state.rows_synced == 2
            assert state.last_sync_timestamp == edited_at

    @patch("posthog.dags.postgres_to_clickhouse_etl.sync_execute")
    @patch("posthog.dags.postgres_to_clickhouse_etl.get_postgres_connection")
    @patch("posthog.dags.postgres_to_clickhouse_etl.create_clickhouse_tables")
    def test_feature_flag_watermark_stays_empty_for_all_null_batch(
        self, mock_create_tables, mock_get_pg, mock_sync_execute
    ):
        """A batch of only never-edited flags still syncs rows but reports no watermark for the run."""
        mock_sync_execute.side_effect = [
            [[None]],
            None,
        ]
        mock_get_pg.return_value = MagicMock()
        with (
            patch("posthog.dags.postgres_to_clickhouse_etl.fetch_rows_in_batches") as mock_fetch,
            patch("posthog.dags.postgres_to_clickhouse_etl.insert_rows_to_clickhouse") as mock_insert,
        ):
            mock_fetch.return_value = iter(
                [[{"id": 7, "team_id": 42, "created_at": datetime(2025, 3, 1), "updated_at": None}]]
            )
            mock_insert.return_value = 1
            context = build_op_context()

            state = _sync_table(context, _config(backward_lookback_seconds=0), "posthog_featureflag")

            assert state.rows_synced == 1
            assert state.last_sync_timestamp is None


class TestVerifySync:
    @patch("posthog.dags.postgres_to_clickhouse_etl.sync_execute")
    def test_reports_all_three_tables(self, mock_sync_execute):
        mock_sync_execute.side_effect = [[[100]], [[150]], [[42]]]

        org = IncrementalState(rows_synced=10, last_sync_timestamp=datetime(2024, 1, 1))
        team = IncrementalState(rows_synced=15, last_sync_timestamp=datetime(2024, 1, 1))
        flag = IncrementalState(rows_synced=42, last_sync_timestamp=datetime(2024, 1, 1))

        result = verify_sync(build_op_context(), org, team, flag)

        assert result["organizations"]["clickhouse_count"] == 100
        assert result["teams"]["clickhouse_count"] == 150
        assert result["feature_flags"]["clickhouse_count"] == 42


class TestDagsterWiring:
    def test_hourly_job_defers_to_three_sync_ops_and_verifies(self):
        assert postgres_to_clickhouse_etl_job is not None
        node_names = {node.name for node in postgres_to_clickhouse_etl_job.graph.nodes}
        assert {"sync_organizations", "sync_teams", "sync_feature_flags", "verify_sync"} <= node_names

    def test_hourly_schedule_wires_to_etl_job(self):
        assert postgres_to_clickhouse_hourly_schedule.job_name == postgres_to_clickhouse_etl_job.name
        assert postgres_to_clickhouse_hourly_schedule.cron_schedule == "0 * * * *"
        assert postgres_to_clickhouse_hourly_schedule.execution_timezone == "UTC"

    @parameterized.expand(
        [
            ("organizations", organizations_in_clickhouse),
            ("teams", teams_in_clickhouse),
            ("feature_flags", feature_flags_in_clickhouse),
        ]
    )
    def test_backfill_assets_are_hourly_partitioned(self, _name, backfill_asset):
        assert backfill_asset.partitions_def is not None
        assert backfill_asset.backfill_policy is not None
        assert backfill_asset.backfill_policy.max_partitions_per_run == 24

    @parameterized.expand(
        [
            (
                "organizations",
                organizations_in_clickhouse,
                "WHERE updated_at >= %s AND updated_at < %s",
            ),
            # Never-edited flags have NULL updated_at in Postgres; a plain-column window would skip them.
            (
                "feature_flags",
                feature_flags_in_clickhouse,
                "WHERE COALESCE(updated_at, created_at) >= %s AND COALESCE(updated_at, created_at) < %s",
            ),
        ]
    )
    def test_asset_window_query_filters_on_watermark_bounds(self, _name, backfill_asset, expected_where):
        mock_pg = MagicMock()
        cur = MagicMock()
        cur.fetchall.return_value = []
        mock_pg.cursor.return_value = cur

        with (
            patch("posthog.dags.postgres_to_clickhouse_etl.get_postgres_connection", return_value=mock_pg),
            patch("posthog.dags.postgres_to_clickhouse_etl.create_clickhouse_tables"),
        ):
            ctx = build_asset_context(partition_key="2024-01-15-14:00")
            backfill_asset(ctx)

        sql, params = cur.execute.call_args[0]
        assert expected_where in sql
        assert params[0].replace(tzinfo=None).isoformat() == "2024-01-15T14:00:00"
        assert params[1].replace(tzinfo=None).isoformat() == "2024-01-15T15:00:00"

    def test_backward_lookback_default_is_one_day(self):
        """Job-level lookback stays at 86400 as the fallback for orgs and teams; flags override on TableConfig."""
        assert _config().backward_lookback_seconds == 86400
