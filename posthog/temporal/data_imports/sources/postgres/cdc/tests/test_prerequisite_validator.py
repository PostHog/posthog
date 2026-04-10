from unittest.mock import MagicMock

from posthog.temporal.data_imports.sources.postgres.cdc.prerequisite_validator import validate_cdc_prerequisites


def _mock_conn(query_results: list[tuple[str, list[tuple]]]):
    """Create a mock connection whose cursor returns results matched by query pattern.

    query_results: ordered list of (pattern, rows) tuples. Each time execute() is
    called, the FIRST matching pattern is used and its rows become the fetchone() results.
    Patterns are matched as substrings of the SQL query string.
    """
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    conn.rollback = MagicMock()
    conn.commit = MagicMock()

    def mock_execute(query, *args, **kwargs):
        query_str = str(query)
        for pattern, rows in query_results:
            if pattern in query_str:
                cursor._current_results = list(rows)
                return
        cursor._current_results = []

    def mock_fetchone():
        if cursor._current_results:
            return cursor._current_results.pop(0)
        return None

    cursor.execute = mock_execute
    cursor.fetchone = mock_fetchone
    cursor._current_results = []

    return conn


# Common result sets
_PG_15 = ("server_version_num", [("150000",)])
_PG_12 = ("server_version_num", [("120000",)])
_WAL_LOGICAL = ("wal_level", [("logical",)])
_WAL_REPLICA = ("wal_level", [("replica",)])
_HAS_PK = ("table_constraints", [(1,)])
_NO_PK = ("table_constraints", [(0,)])
_HAS_REPL_ROLE = ("rolreplication", [(True,)])
_NO_REPL_ROLE = ("rolreplication", [(False,)])
_MAX_SLOTS_10 = ("max_replication_slots", [("10",)])
_SLOT_COUNT_2 = ("COUNT", [("2",)])
_SLOT_COUNT_10 = ("COUNT", [("10",)])
_SLOT_EXISTS = ("slot_name", [(1,)])
_SLOT_NOT_EXISTS: tuple[str, list] = ("slot_name", [])
_PUB_EXISTS = ("pubname", [(1,)])
_PUB_NOT_EXISTS: tuple[str, list] = ("pubname", [])


class TestValidateCDCPrerequisites:
    def test_all_checks_pass_posthog_managed(self):
        conn = _mock_conn([_PG_15, _WAL_LOGICAL, _HAS_PK, _HAS_REPL_ROLE, _MAX_SLOTS_10, _SLOT_COUNT_2])
        errors = validate_cdc_prerequisites(conn=conn, management_mode="posthog", tables=["users"], schema="public")
        assert errors == []

    def test_all_checks_pass_self_managed(self):
        conn = _mock_conn([_PG_15, _WAL_LOGICAL, _HAS_PK, _SLOT_EXISTS, _PUB_EXISTS])
        errors = validate_cdc_prerequisites(
            conn=conn,
            management_mode="self_managed",
            tables=["users"],
            schema="public",
            slot_name="my_slot",
            publication_name="my_pub",
        )
        assert errors == []

    def test_pg_version_too_old(self):
        conn = _mock_conn([_PG_12, _WAL_LOGICAL, _HAS_PK, _HAS_REPL_ROLE, _MAX_SLOTS_10, _SLOT_COUNT_2])
        errors = validate_cdc_prerequisites(conn=conn, management_mode="posthog", tables=["users"])
        assert any("PostgreSQL 13" in e for e in errors)

    def test_wal_level_not_logical(self):
        conn = _mock_conn([_PG_15, _WAL_REPLICA, _HAS_PK, _HAS_REPL_ROLE, _MAX_SLOTS_10, _SLOT_COUNT_2])
        errors = validate_cdc_prerequisites(conn=conn, management_mode="posthog", tables=["users"])
        assert any("wal_level" in e for e in errors)

    def test_table_missing_primary_key(self):
        conn = _mock_conn([_PG_15, _WAL_LOGICAL, _NO_PK, _HAS_REPL_ROLE, _MAX_SLOTS_10, _SLOT_COUNT_2])
        errors = validate_cdc_prerequisites(conn=conn, management_mode="posthog", tables=["orders"])
        assert any("primary key" in e for e in errors)

    def test_no_replication_role(self):
        conn = _mock_conn([_PG_15, _WAL_LOGICAL, _HAS_PK, _NO_REPL_ROLE, _MAX_SLOTS_10, _SLOT_COUNT_2])
        errors = validate_cdc_prerequisites(conn=conn, management_mode="posthog", tables=["users"])
        assert any("REPLICATION" in e for e in errors)

    def test_no_replication_slot_capacity(self):
        conn = _mock_conn([_PG_15, _WAL_LOGICAL, _HAS_PK, _HAS_REPL_ROLE, _MAX_SLOTS_10, _SLOT_COUNT_10])
        errors = validate_cdc_prerequisites(conn=conn, management_mode="posthog", tables=["users"])
        assert any("capacity" in e for e in errors)

    def test_self_managed_missing_slot_name(self):
        conn = _mock_conn([_PG_15, _WAL_LOGICAL, _HAS_PK])
        errors = validate_cdc_prerequisites(
            conn=conn,
            management_mode="self_managed",
            tables=["users"],
            slot_name=None,
            publication_name="my_pub",
        )
        assert any("slot name is required" in e.lower() for e in errors)

    def test_self_managed_missing_publication_name(self):
        conn = _mock_conn([_PG_15, _WAL_LOGICAL, _HAS_PK])
        errors = validate_cdc_prerequisites(
            conn=conn,
            management_mode="self_managed",
            tables=["users"],
            slot_name="my_slot",
            publication_name=None,
        )
        assert any("publication name is required" in e.lower() for e in errors)

    def test_self_managed_slot_does_not_exist(self):
        conn = _mock_conn([_PG_15, _WAL_LOGICAL, _HAS_PK, _SLOT_NOT_EXISTS, _PUB_EXISTS])
        errors = validate_cdc_prerequisites(
            conn=conn,
            management_mode="self_managed",
            tables=["users"],
            slot_name="nonexistent_slot",
            publication_name="my_pub",
        )
        assert any("does not exist" in e for e in errors)

    def test_self_managed_publication_does_not_exist(self):
        conn = _mock_conn([_PG_15, _WAL_LOGICAL, _HAS_PK, _SLOT_EXISTS, _PUB_NOT_EXISTS])
        errors = validate_cdc_prerequisites(
            conn=conn,
            management_mode="self_managed",
            tables=["users"],
            slot_name="my_slot",
            publication_name="nonexistent_pub",
        )
        assert any("does not exist" in e for e in errors)

    def test_empty_tables_list(self):
        conn = _mock_conn([_PG_15, _WAL_LOGICAL, _HAS_REPL_ROLE, _MAX_SLOTS_10, _SLOT_COUNT_2])
        errors = validate_cdc_prerequisites(conn=conn, management_mode="posthog", tables=[])
        assert errors == []
