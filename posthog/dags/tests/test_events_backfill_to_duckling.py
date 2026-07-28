import re
import uuid
from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass
from typing import Any

import pytest
from unittest.mock import patch

from django.db import connection as django_connection

import psycopg
from dagster import build_asset_context
from parameterized import parameterized

from posthog.dags.events_backfill_to_duckling import (
    DucklingTarget,
    _fixup_partition_values_for_added_files,
    _resolve_duckling_target,
)


@dataclass
class _FakeRow:
    bucket: str | None
    bucket_region: str


class TestResolveDucklingTarget:
    def _resolve(
        self,
        server: "_FakeRow | None",
        cp_bucket: str | None = None,
    ):
        with (
            patch("posthog.dags.events_backfill_to_duckling._get_org_id_for_team", return_value="org-1"),
            patch("posthog.dags.events_backfill_to_duckling.get_duckgres_server_for_organization", return_value=server),
            patch(
                "products.data_warehouse.backend.presentation.views.managed_warehouse.cp_bucket_for",
                return_value=cp_bucket,
            ) as mock_cp,
            # The per-environment table-name lookup hits the DB; this suite stays DB-free.
            patch("posthog.dags.events_backfill_to_duckling._resolve_table_names", return_value=("events", "persons")),
        ):
            target = _resolve_duckling_target(team_id=123)
        return target, mock_cp

    @parameterized.expand(
        [
            # The control plane wins over a stored DuckgresServer bucket — a stale,
            # locally-derived stored value must never beat the authoritative name.
            ("server_present_but_stale", _FakeRow("stale-stored-bucket", "eu-west-1")),
            ("no_server", None),
            ("server_blank", _FakeRow("", "eu-west-1")),
        ]
    )
    def test_control_plane_wins_over_stored_server(self, _name: str, server: "_FakeRow | None") -> None:
        target, mock_cp = self._resolve(server=server, cp_bucket="cp-bucket")

        mock_cp.assert_called_once_with("org-1")
        assert target.bucket == "cp-bucket"
        assert target.organization_id == "org-1"

    def test_falls_back_to_stored_server_when_control_plane_unavailable(self) -> None:
        # CP returns nothing (unreachable/unconfigured) — use the known-good stored row.
        target, mock_cp = self._resolve(server=_FakeRow("server-bucket", "eu-west-1"), cp_bucket=None)

        mock_cp.assert_called_once_with("org-1")
        assert target.bucket == "server-bucket"
        assert target.bucket_region == "eu-west-1"

    @parameterized.expand(
        [
            ("no_rows", None),
            ("server_with_null_bucket", _FakeRow(None, "us-east-1")),
            ("server_blank", _FakeRow("", "us-east-1")),
        ]
    )
    def test_raises_when_nothing_can_name_the_bucket(self, _name: str, server: "_FakeRow | None") -> None:
        with pytest.raises(ValueError, match="No S3 bucket resolvable"):
            self._resolve(server=server, cp_bucket=None)


# Verbatim from the DuckLake specification (docs/stable/specification/tables/overview.html),
# limited to the tables the ducklake_file_partition_value fix-up touches. The fix-up's SQL is
# validated against this real DDL — a query referencing a column the spec doesn't define
# (the UndefinedColumn class of bug) fails here instead of in production.
_DUCKLAKE_CATALOG_DDL = [
    "CREATE TABLE public.ducklake_schema (schema_id BIGINT PRIMARY KEY, schema_uuid UUID, begin_snapshot BIGINT, end_snapshot BIGINT, schema_name VARCHAR, path VARCHAR, path_is_relative BOOLEAN)",
    "CREATE TABLE public.ducklake_table (table_id BIGINT, table_uuid UUID, begin_snapshot BIGINT, end_snapshot BIGINT, schema_id BIGINT, table_name VARCHAR, path VARCHAR, path_is_relative BOOLEAN)",
    "CREATE TABLE public.ducklake_partition_info (partition_id BIGINT, table_id BIGINT, begin_snapshot BIGINT, end_snapshot BIGINT)",
    'CREATE TABLE public.ducklake_partition_column (partition_id BIGINT, table_id BIGINT, partition_key_index BIGINT, column_id BIGINT, "transform" VARCHAR)',
    "CREATE TABLE public.ducklake_data_file (data_file_id BIGINT PRIMARY KEY, table_id BIGINT, begin_snapshot BIGINT, end_snapshot BIGINT, file_order BIGINT, path VARCHAR, path_is_relative BOOLEAN, file_format VARCHAR, record_count BIGINT, file_size_bytes BIGINT, footer_size BIGINT, row_id_start BIGINT, partition_id BIGINT, encryption_key VARCHAR, mapping_id BIGINT, partial_max BIGINT)",
    "CREATE TABLE public.ducklake_file_partition_value (data_file_id BIGINT, table_id BIGINT, partition_key_index BIGINT, partition_value VARCHAR)",
]

_DUCKLAKE_CATALOG_TABLES = [
    match.group(1)
    for stmt in _DUCKLAKE_CATALOG_DDL
    for match in [re.search(r"CREATE TABLE (public\.\w+)", stmt)]
    if match
]


def _connect_test_db() -> psycopg.Connection[Any]:
    settings_dict = django_connection.settings_dict
    return psycopg.connect(
        host=settings_dict["HOST"] or "localhost",
        port=int(settings_dict["PORT"] or 5432),
        dbname=settings_dict["NAME"],
        user=settings_dict["USER"],
        password=settings_dict["PASSWORD"],
        autocommit=True,
    )


def _drop_catalog_tables(conn: psycopg.Connection[Any]) -> None:
    with conn.cursor() as cur:
        cur.execute(f"DROP TABLE IF EXISTS {', '.join(_DUCKLAKE_CATALOG_TABLES)}")


@pytest.fixture
def ducklake_catalog(django_db_setup: None) -> Iterator[psycopg.Connection[Any]]:
    with closing(_connect_test_db()) as conn:
        # Pre-drop: leftovers from an interrupted run survive --reuse-db.
        _drop_catalog_tables(conn)
        with conn.cursor() as cur:
            for stmt in _DUCKLAKE_CATALOG_DDL:
                cur.execute(stmt)
        try:
            yield conn
        finally:
            _drop_catalog_tables(conn)


class TestFixupPartitionValuesForAddedFiles:
    TABLE_ID = 10
    PARTITION_ID = 100

    def _seed_catalog(self, conn: psycopg.Connection[Any]) -> None:
        with conn.cursor() as cur:
            # A dropped-and-recreated 'posthog' schema: only the live row may resolve.
            cur.executemany(
                "INSERT INTO public.ducklake_schema VALUES (%s, %s, %s, %s, %s, %s, %s)",
                [
                    (2, uuid.uuid4(), 1, 5, "posthog", "posthog/", True),
                    (1, uuid.uuid4(), 5, None, "posthog", "posthog/", True),
                ],
            )
            cur.execute(
                "INSERT INTO public.ducklake_table VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (self.TABLE_ID, uuid.uuid4(), 1, None, 1, "events", "events/", True),
            )
            # A superseded partition_info generation next to the live one.
            cur.executemany(
                "INSERT INTO public.ducklake_partition_info VALUES (%s, %s, %s, %s)",
                [(99, self.TABLE_ID, 1, 5), (self.PARTITION_ID, self.TABLE_ID, 5, None)],
            )
            cur.executemany(
                "INSERT INTO public.ducklake_partition_column VALUES (%s, %s, %s, %s, %s)",
                [
                    (self.PARTITION_ID, self.TABLE_ID, 0, 7, "year"),
                    (self.PARTITION_ID, self.TABLE_ID, 1, 7, "month"),
                    (self.PARTITION_ID, self.TABLE_ID, 2, 7, "day"),
                ],
            )
            cur.executemany(
                "INSERT INTO public.ducklake_data_file "
                "(data_file_id, table_id, begin_snapshot, end_snapshot, path, path_is_relative, partition_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                [
                    (1000, self.TABLE_ID, 5, None, self._path(day=5), True, self.PARTITION_ID),
                    (1001, self.TABLE_ID, 5, None, self._path(day=6), True, self.PARTITION_ID),
                    (1002, self.TABLE_ID, 5, None, self._path(day=7), True, self.PARTITION_ID),
                ],
            )
            # File 1000 carries the upstream bug's signature (every value piled onto the
            # highest key index); file 1001 has no rows at all; file 1002 is untargeted
            # and correct — it must survive the fix-up untouched.
            cur.executemany(
                "INSERT INTO public.ducklake_file_partition_value VALUES (%s, %s, %s, %s)",
                [
                    (1000, self.TABLE_ID, 2, "2025"),
                    (1000, self.TABLE_ID, 2, "1"),
                    (1000, self.TABLE_ID, 2, "5"),
                    (1002, self.TABLE_ID, 0, "2025"),
                    (1002, self.TABLE_ID, 1, "1"),
                    (1002, self.TABLE_ID, 2, "7"),
                ],
            )

    @staticmethod
    def _path(day: int) -> str:
        return f"backfill/events/2/year=2025/month=01/day={day:02d}/part-00.parquet"

    @staticmethod
    def _partition_values(conn: psycopg.Connection[Any]) -> set[tuple[int, int, int, str]]:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT data_file_id, table_id, partition_key_index, partition_value "
                "FROM public.ducklake_file_partition_value"
            )
            return {tuple(row) for row in cur.fetchall()}

    def _run_fixup(self, file_paths: list[str]) -> None:
        target = DucklingTarget(
            team_id=2,
            organization_id="org-1",
            bucket="test-bucket",
            bucket_region="us-east-1",
        )
        with patch(
            "posthog.dags.events_backfill_to_duckling._open_catalog_conn",
            side_effect=lambda _target: _connect_test_db(),
        ):
            _fixup_partition_values_for_added_files(build_asset_context(), target, "events", "events", file_paths)

    def test_rebuilds_partition_values_from_paths(self, ducklake_catalog: psycopg.Connection[Any]) -> None:
        self._seed_catalog(ducklake_catalog)

        self._run_fixup([self._path(day=5), self._path(day=6)])

        expected = {
            (1000, self.TABLE_ID, 0, "2025"),
            (1000, self.TABLE_ID, 1, "1"),
            (1000, self.TABLE_ID, 2, "5"),
            (1001, self.TABLE_ID, 0, "2025"),
            (1001, self.TABLE_ID, 1, "1"),
            (1001, self.TABLE_ID, 2, "6"),
            (1002, self.TABLE_ID, 0, "2025"),
            (1002, self.TABLE_ID, 1, "1"),
            (1002, self.TABLE_ID, 2, "7"),
        }
        assert self._partition_values(ducklake_catalog) == expected

        # Re-running over the same paths must converge to the same state (retry contract).
        self._run_fixup([self._path(day=5), self._path(day=6)])
        assert self._partition_values(ducklake_catalog) == expected
