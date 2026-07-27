from types import SimpleNamespace

from parameterized import parameterized

from products.data_warehouse.backend.direct_query_engines import get_direct_query_engine


def _source_schema(*, catalog=None, schema=None, table=None):
    return SimpleNamespace(source_catalog=catalog, source_schema=schema, source_table_name=table)


class TestDirectQueryEngineRegistry:
    @parameterized.expand(["postgres", "mysql", "snowflake", "redshift"])
    def test_known_engine_resolves(self, engine: str):
        adapter = get_direct_query_engine(engine)
        assert adapter is not None
        assert adapter.engine == engine

    @parameterized.expand([("none", None), ("unknown", "bigquery")])
    def test_non_direct_engine_returns_none(self, _name: str, engine):
        assert get_direct_query_engine(engine) is None

    @parameterized.expand(
        [
            # Only Postgres resolves its upstream location in warehouse mode; the view keys the
            # warehouse-vs-direct decision off this flag instead of a source-type check.
            ("postgres", True),
            ("mysql", False),
            ("snowflake", False),
            ("redshift", False),
        ]
    )
    def test_resolves_location_in_warehouse_mode(self, engine: str, expected: bool):
        adapter = get_direct_query_engine(engine)
        assert adapter is not None
        assert adapter.resolves_location_in_warehouse_mode is expected

    @parameterized.expand(
        [
            # Explicit metadata wins for every engine; MySQL has no catalog layer so it always
            # returns None there even when catalog metadata is present.
            ("postgres", ("db", "public", "users")),
            ("snowflake", ("db", "public", "users")),
            ("redshift", ("db", "public", "users")),
            ("mysql", (None, "public", "users")),
        ]
    )
    def test_source_table_location_uses_explicit_metadata(self, engine: str, expected: tuple):
        adapter = get_direct_query_engine(engine)
        assert adapter is not None
        location = adapter.source_table_location(
            schema_name="ignored",
            source_schema=_source_schema(catalog="db", schema="public", table="users"),
            default_schema=None,
            default_catalog=None,
        )
        assert location == expected

    def test_mysql_falls_back_to_default_catalog_as_schema(self):
        # MySQL has no schema config field, so `database` (passed as default_catalog) is the
        # schema fallback when no default_schema is given.
        adapter = get_direct_query_engine("mysql")
        assert adapter is not None
        location = adapter.source_table_location(
            schema_name="orders",
            source_schema=None,
            default_schema=None,
            default_catalog="shop_db",
        )
        assert location == (None, "shop_db", "orders")

    def test_snowflake_splits_dotted_name_when_no_default_schema(self):
        # Snowflake infers schema from a dotted `schema.table` name only when no default schema
        # is configured — the bespoke resolution this migration preserved.
        adapter = get_direct_query_engine("snowflake")
        assert adapter is not None
        location = adapter.source_table_location(
            schema_name="analytics.events",
            source_schema=None,
            default_schema=None,
            default_catalog="WAREHOUSE",
        )
        assert location == ("WAREHOUSE", "analytics", "events")

    @parameterized.expand(["mysql", "snowflake", "redshift"])
    def test_non_postgres_engines_return_no_name_substitutions(self, engine: str):
        # Returning None (not {}) is the sentinel that makes the view fall through to the generic
        # multi-schema migration path; only Postgres has bespoke legacy-row remapping.
        adapter = get_direct_query_engine(engine)
        assert adapter is not None
        assert adapter.refresh_name_substitutions(source=None, source_schemas=[], team_id=1) is None

    def test_snowflake_default_schema_takes_precedence_over_dot_split(self):
        adapter = get_direct_query_engine("snowflake")
        assert adapter is not None
        location = adapter.source_table_location(
            schema_name="analytics.events",
            source_schema=None,
            default_schema="public",
            default_catalog=None,
        )
        assert location == (None, "public", "analytics.events")
