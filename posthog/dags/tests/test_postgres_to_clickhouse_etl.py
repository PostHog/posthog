"""Tests for the table-driven Postgres to ClickHouse ETL pipeline."""

import json
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from unittest.mock import MagicMock, patch

from dagster import build_asset_context, build_op_context
from parameterized import parameterized

from posthog.dags.postgres_to_clickhouse_etl import (
    IncrementalState,
    PostgresToClickHouseETLConfig,
    _sync_table,
    create_clickhouse_tables,
    fetch_rows_in_batches,
    get_feature_flag_table_sql,
    get_organization_table_sql,
    get_team_table_sql,
    insert_rows_to_clickhouse,
    organizations_in_clickhouse,
    postgres_to_clickhouse_etl_job,
    postgres_to_clickhouse_hourly_schedule,
    teams_in_clickhouse,
    transform_feature_flag_row,
    transform_organization_row,
    transform_row,
    transform_team_row,
    verify_sync,
)


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
            "available_product_features": '[{"key": "feature1"}]',  # ::text on the PG side
            "usage": '{"events": 1000}',
            "personalization": '{"role": "engineer"}',
            "domain_whitelist": ["example.com"],
        }

        transformed = transform_organization_row(row)

        assert transformed["id"] == str(test_uuid)
        assert isinstance(transformed["logo_media_id"], str)
        assert transformed["is_member_join_email_enabled"] == 1
        assert transformed["is_hipaa"] == 0
        # ::text columns pass through untouched — no parse-then-redump.
        assert transformed["available_product_features"] == row["available_product_features"]
        assert transformed["usage"] == row["usage"]
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
            "session_recording_sample_rate": Decimal("0.50"),
            "drop_events_older_than": timedelta(days=30),
        }

        transformed = transform_team_row(row)

        assert transformed["uuid"] == str(team_uuid)
        assert transformed["organization_id"] == str(org_uuid)
        assert transformed["anonymize_ips"] == 1
        assert transformed["session_recording_opt_in"] == 0
        assert transformed["test_account_filters"] == row["test_account_filters"]
        assert transformed["app_urls"] == ["https://app.example.com"]
        assert transformed["person_display_name_properties"] == []
        assert transformed["session_recording_sample_rate"] == Decimal("0.50")
        assert transformed["drop_events_older_than"] == 30 * 24 * 60 * 60

    def test_transform_feature_flag_row_null_updated_at_coalesces_to_created_at(self):
        # updated_at is NULL until a flag's first edit; the mirror must not store NULL because the
        # watermark read depends on it.
        created = datetime(2025, 3, 1, 12, 0, 0)
        row = _flag_row(created_at=created, updated_at=None)

        transformed = transform_feature_flag_row(row)

        assert transformed["updated_at"] == created

    def test_transform_feature_flag_row_serializes_filters(self):
        original_filters = {
            "groups": [{"properties": [{"key": "email", "value": "@posthog.com", "type": "person"}]}],
            "multivariate": {"variants": [{"key": "control"}, {"key": "test"}]},
        }
        row = _flag_row(filters=original_filters)

        transformed = transform_feature_flag_row(row)

        # transform mutates the row in place (filters becomes a JSON string), so parse it back and compare to the original dict.
        assert json.loads(transformed["filters"]) == original_filters
        assert transformed["variant_count"] == 2

    @parameterized.expand(
        [
            (
                "flag_dependency",
                {"groups": [{"properties": [{"key": "123", "value": "123", "type": "flag"}]}]},
                "has_flag_dependency",
                1,
            ),
            (
                "no_flag_dependency",
                {"groups": [{"properties": [{"key": "email", "value": "x", "type": "person"}]}]},
                "has_flag_dependency",
                0,
            ),
            (
                "cohort_ref",
                {"groups": [{"properties": [{"key": "id", "value": 14, "type": "cohort"}]}]},
                "has_cohort_filters",
                1,
            ),
            (
                "plain_person_property",
                {"groups": [{"properties": [{"key": "email", "value": "x", "type": "person"}]}]},
                "has_cohort_filters",
                0,
            ),
            (
                "multivariate",
                {"groups": [], "multivariate": {"variants": [{"key": "a"}, {"key": "b"}, {"key": "c"}]}},
                "variant_count",
                3,
            ),
            ("boolean_flag_no_variants", {"groups": []}, "variant_count", 0),
        ]
    )
    def test_transform_feature_flag_projection(self, _name, filters, projection_column, expected):
        transformed = transform_feature_flag_row(_flag_row(filters=filters))
        assert transformed[projection_column] == expected

    def test_transform_feature_flag_row_unparseable_filters_falls_back_to_empty_dict(self):
        transformed = transform_feature_flag_row(_flag_row(filters="not json"))

        assert transformed["filters"] == "{}"
        assert transformed["has_flag_dependency"] == 0
        assert transformed["has_cohort_filters"] == 0
        assert transformed["variant_count"] == 0

    def test_transform_feature_flag_row_drops_last_called_at(self):
        # last_called_at has its own bulk-update writer that skips updated_at; a mirrored column
        # would be permanently stale, so the transform strips it.
        row = _flag_row(last_called_at=datetime(2025, 3, 2))

        transformed = transform_feature_flag_row(row)

        assert "last_called_at" not in transformed

    def test_transform_row_unknown_table_raises(self):
        with pytest.raises(KeyError):
            transform_row("posthog_nonexistent", {})


class TestTableDdl:
    def test_organization_ddl(self):
        sql = get_organization_table_sql()
        assert "models.posthog_organization" in sql
        assert "ReplicatedReplacingMergeTree" in sql

    def test_team_ddl(self):
        sql = get_team_table_sql()
        assert "models.posthog_team" in sql
        assert "ReplicatedReplacingMergeTree" in sql

    def test_feature_flag_ddl_shape(self):
        sql = get_feature_flag_table_sql()
        assert "models.posthog_featureflag" in sql
        assert "ReplicatedReplacingMergeTree" in sql
        assert "key String" in sql
        assert "filters String" in sql
        # Flag identity is (team_id, id), not (team_id, key) — see TableConfig note on tombstone renames.
        assert "ORDER BY (team_id, id, updated_at)" in sql
        assert "has_flag_dependency" in sql
        assert "has_cohort_filters" in sql
        assert "variant_count" in sql


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
        # The filter must pick up either one moving into the window.
        conn, cursor = self._conn_yielding([[{"id": 1}]])
        list(fetch_rows_in_batches(conn, "posthog_featureflag", datetime(2024, 1, 1), batch_size=100))

        sql, params = cursor.execute.call_args[0]
        assert "WHERE (updated_at > %s OR (updated_at IS NULL AND created_at > %s))" in sql
        assert params == [datetime(2024, 1, 1)] * 2

    def test_jsonb_columns_selected_as_text_to_skip_parse(self):
        """Org/team JSON columns go over the wire as text so psycopg2 doesn't parse them only to re-serialize."""
        conn, cursor = self._conn_yielding([[{"id": 1}]])
        list(fetch_rows_in_batches(conn, "posthog_team", None, batch_size=100))

        sql = cursor.execute.call_args[0][0]
        assert "test_account_filters::text AS test_account_filters" in sql

    def test_flag_filters_not_cast_to_text_because_projections_need_the_dict(self):
        conn, cursor = self._conn_yielding([[{"id": 1}]])
        list(fetch_rows_in_batches(conn, "posthog_featureflag", None, batch_size=100))

        sql = cursor.execute.call_args[0][0]
        assert "filters::text" not in sql
        assert " filters" in sql

    def test_named_server_side_cursor_used(self):
        conn, _ = self._conn_yielding([[{"id": 1}]])
        list(fetch_rows_in_batches(conn, "posthog_organization", None, batch_size=100))
        assert conn.cursor.call_args[1].get("name") is not None


class TestInsertRowsToClickHouse:
    @patch("posthog.dags.postgres_to_clickhouse_etl.sync_execute")
    def test_empty_rows_returns_zero(self, mock_sync_execute):
        assert insert_rows_to_clickhouse("posthog_organization", [], batch_size=10) == 0
        mock_sync_execute.assert_not_called()

    @patch("posthog.dags.postgres_to_clickhouse_etl.sync_execute")
    def test_insert_targets_models_db_with_parameterized_values(self, mock_sync_execute):
        row = {
            "id": 1,
            "name": "Org",
            "is_member_join_email_enabled": True,
            "available_product_features": "[]",
            "created_at": datetime(2024, 1, 1),
            "updated_at": datetime(2024, 1, 2),
        }

        n = insert_rows_to_clickhouse("posthog_organization", [row], batch_size=10)

        assert n == 1
        call = mock_sync_execute.call_args[0]
        assert "INSERT INTO models.posthog_organization" in call[0]
        assert "VALUES" in call[0]
        # Data is passed as a separate argument, not inlined into SQL text — lets the driver's
        # columnar writer handle arrays / datetimes / strings with embedded quotes.
        assert call[1] is not None

    @patch("posthog.dags.postgres_to_clickhouse_etl.sync_execute")
    def test_insert_batches_by_batch_size(self, mock_sync_execute):
        rows = [
            {
                "id": i,
                "name": f"Org {i}",
                "is_member_join_email_enabled": True,
                "created_at": datetime(2024, 1, 1),
                "updated_at": datetime(2024, 1, 1),
            }
            for i in range(25)
        ]

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
    def test_feature_flag_watermark_uses_updated_at_when_present(
        self, mock_create_tables, mock_get_pg, mock_sync_execute
    ):
        """updated_at is the watermark for edited flags; created_at only matters for flags that were never edited."""
        mock_sync_execute.side_effect = [
            [[None]],
            None,
        ]
        mock_get_pg.return_value = MagicMock()
        edited_at = datetime(2025, 4, 15, 10, 0, 0)
        created_at = datetime(2025, 3, 1, 12, 0, 0)
        with (
            patch("posthog.dags.postgres_to_clickhouse_etl.fetch_rows_in_batches") as mock_fetch,
            patch("posthog.dags.postgres_to_clickhouse_etl.insert_rows_to_clickhouse") as mock_insert,
        ):
            mock_fetch.return_value = iter(
                [
                    [
                        {
                            "id": 7,
                            "team_id": 42,
                            "key": "flag",
                            "created_at": created_at,
                            "updated_at": edited_at,
                            "filters": {},
                        }
                    ]
                ]
            )
            mock_insert.return_value = 1
            context = build_op_context()

            state = _sync_table(context, _config(backward_lookback_seconds=0), "posthog_featureflag")

            assert state.rows_synced == 1
            # The high-watermark advances to updated_at, not created_at — even though the flag config
            # falls back to created_at for writing, the *read* watermark uses updated_at verbatim.
            assert state.last_sync_timestamp == edited_at


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

    def test_organizations_and_teams_assets_still_defined(self):
        assert organizations_in_clickhouse.partitions_def is not None
        assert teams_in_clickhouse.partitions_def is not None
        assert organizations_in_clickhouse.backfill_policy is not None
        assert organizations_in_clickhouse.backfill_policy.max_partitions_per_run == 24

    def test_asset_window_query_filters_on_watermark_bounds(self):
        mock_pg = MagicMock()
        cur = MagicMock()
        cur.fetchall.return_value = []
        mock_pg.cursor.return_value = cur

        with (
            patch("posthog.dags.postgres_to_clickhouse_etl.get_postgres_connection", return_value=mock_pg),
            patch("posthog.dags.postgres_to_clickhouse_etl.create_clickhouse_tables"),
        ):
            ctx = build_asset_context(partition_key="2024-01-15-14:00")
            organizations_in_clickhouse(ctx)

        sql, params = cur.execute.call_args[0]
        assert "WHERE updated_at >= %s AND updated_at < %s" in sql
        assert params[0].isoformat() == "2024-01-15T14:00:00"
        assert params[1].isoformat() == "2024-01-15T15:00:00"

    def test_backward_lookback_default_is_one_day(self):
        assert _config().backward_lookback_seconds == 86400
