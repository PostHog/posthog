from posthog.test.base import BaseTest

from django.db import models

from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DateTimeDatabaseField,
    IntegerDatabaseField,
    StringDatabaseField,
)
from posthog.hogql.database.schema.django_tables import (
    DjangoTable,
    clear_django_tables_cache,
    django_field_to_hogql,
    get_django_tables,
)


class TestDjangoFieldToHogql(BaseTest):
    def test_integer_field(self):
        field = models.IntegerField(name="count")
        field.column = "count"
        field.null = False

        result = django_field_to_hogql(field)

        self.assertIsInstance(result, IntegerDatabaseField)
        self.assertEqual(result.name, "count")
        self.assertFalse(result.nullable)

    def test_char_field(self):
        field = models.CharField(name="name", max_length=100)
        field.column = "name"
        field.null = True

        result = django_field_to_hogql(field)

        self.assertIsInstance(result, StringDatabaseField)
        self.assertEqual(result.name, "name")
        self.assertTrue(result.nullable)

    def test_boolean_field(self):
        field = models.BooleanField(name="active")
        field.column = "active"
        field.null = False

        result = django_field_to_hogql(field)

        self.assertIsInstance(result, BooleanDatabaseField)

    def test_datetime_field(self):
        field = models.DateTimeField(name="created_at")
        field.column = "created_at"
        field.null = True

        result = django_field_to_hogql(field)

        self.assertIsInstance(result, DateTimeDatabaseField)


class TestDjangoTable(BaseTest):
    def test_to_printed_clickhouse_returns_db_table(self):
        table = DjangoTable(
            fields={},
            db_table="posthog_dashboard",
            hogql_name="dashboard",
            resource="dashboard",
        )

        result = table.to_printed_clickhouse(None)

        self.assertEqual(result, "posthog_dashboard")

    def test_to_printed_hogql_returns_hogql_name(self):
        table = DjangoTable(
            fields={},
            db_table="posthog_dashboard",
            hogql_name="dashboard",
            resource="dashboard",
        )

        result = table.to_printed_hogql()

        self.assertEqual(result, "dashboard")


class TestGetDjangoTables(BaseTest):
    def setUp(self):
        super().setUp()
        # Clear cache before each test
        clear_django_tables_cache()

    def tearDown(self):
        super().tearDown()
        clear_django_tables_cache()

    def test_returns_dict_of_tables(self):
        tables = get_django_tables()

        self.assertIsInstance(tables, dict)

    def test_includes_dashboard_table(self):
        tables = get_django_tables()

        # Dashboard should be included as it has team and is access controlled
        self.assertIn("dashboard", tables)
        self.assertIsInstance(tables["dashboard"], DjangoTable)
        self.assertEqual(tables["dashboard"].resource, "dashboard")

    def test_caches_results(self):
        tables1 = get_django_tables()
        tables2 = get_django_tables()

        self.assertIs(tables1, tables2)
