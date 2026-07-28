from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql.direct_sql import (
    ClickHouseAdapter,
    MySQLAdapter,
    PostgresAdapter,
    registry as registry_module,
)
from posthog.hogql.direct_sql.capability import direct_capable_source_types, is_direct_capable
from posthog.hogql.direct_sql.registry import get_adapter, register_adapter, registered_engines

from products.warehouse_sources.backend.facade.models import ExternalDataSource
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType


class TestDirectSQLRegistry(SimpleTestCase):
    def test_get_adapter_returns_registered_engine_adapter(self):
        self.assertIsInstance(get_adapter("postgres"), PostgresAdapter)
        self.assertIsInstance(get_adapter("mysql"), MySQLAdapter)
        self.assertIsInstance(get_adapter("clickhouse"), ClickHouseAdapter)

    @parameterized.expand([("none", None), ("unregistered", "bigquery")])
    def test_get_adapter_returns_none_for_unknown_engine(self, _name, engine):
        self.assertIsNone(get_adapter(engine))

    def test_registered_engines_includes_all_engines(self):
        self.assertEqual({"postgres", "mysql", "snowflake", "redshift", "clickhouse"}, set(registered_engines()))

    def test_clickhouse_adapter_compiles_hogql(self):
        adapter = get_adapter("clickhouse")
        assert adapter is not None
        # dialect is non-None, so direct_supports_hogql is True (not raw-only).
        self.assertEqual(adapter.dialect, "clickhouse")

    def test_register_adapter_round_trips(self):
        class FakeAdapter:
            engine = "fake"
            dialect = None

        try:
            register_adapter(FakeAdapter())  # type: ignore[arg-type]
            self.assertIs(type(get_adapter("fake")), FakeAdapter)
        finally:
            registry_module._ADAPTERS.pop("fake", None)


class TestDirectSQLCapability(SimpleTestCase):
    @parameterized.expand(
        [
            ("postgres_direct_ignores_toggle", ExternalDataSourceType.POSTGRES, "direct", False, True),
            ("postgres_synced_enabled", ExternalDataSourceType.POSTGRES, "warehouse", True, True),
            ("postgres_synced_disabled", ExternalDataSourceType.POSTGRES, "warehouse", False, False),
            ("mysql_synced_enabled", ExternalDataSourceType.MYSQL, "warehouse", True, True),
            ("snowflake_direct_ignores_toggle", ExternalDataSourceType.SNOWFLAKE, "direct", False, True),
            ("clickhouse_direct_ignores_toggle", ExternalDataSourceType.CLICKHOUSE, "direct", False, True),
            ("clickhouse_synced_enabled", ExternalDataSourceType.CLICKHOUSE, "warehouse", True, True),
            ("clickhouse_synced_disabled", ExternalDataSourceType.CLICKHOUSE, "warehouse", False, False),
            ("clickhousecloud_direct", ExternalDataSourceType.CLICKHOUSECLOUD, "direct", False, True),
            ("unmapped_engine_synced", ExternalDataSourceType.STRIPE, "warehouse", True, False),
            ("unmapped_engine_direct", ExternalDataSourceType.STRIPE, "direct", True, False),
        ]
    )
    def test_is_direct_capable(self, _name, source_type, access_method, direct_query_enabled, expected):
        source = ExternalDataSource(
            source_type=source_type,
            access_method=access_method,
            direct_query_enabled=direct_query_enabled,
        )
        self.assertIs(is_direct_capable(source), expected)

    def test_direct_capable_source_types(self):
        self.assertEqual(
            {
                ExternalDataSourceType.POSTGRES,
                ExternalDataSourceType.MYSQL,
                ExternalDataSourceType.SNOWFLAKE,
                ExternalDataSourceType.REDSHIFT,
                ExternalDataSourceType.CLICKHOUSE,
                ExternalDataSourceType.CLICKHOUSECLOUD,
            },
            set(direct_capable_source_types()),
        )
