from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql.database.models import DatabaseField, StringDatabaseField, UnknownDatabaseField

from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery


class TestSavedQueryHogqlDefinition(SimpleTestCase):
    @parameterized.expand(
        [
            ("known_field_class", "StringDatabaseField", StringDatabaseField),
            # A field-class name the mapping doesn't know about must degrade to UnknownDatabaseField
            # instead of raising KeyError. During a rolling deploy an old pod can read column metadata
            # a new pod regenerated with a hogql class name the old mapping lacks (e.g. UUIDDatabaseField
            # in #72528) — an unguarded dict index there crashed the core web analytics query path.
            ("unrecognized_field_class", "SomeFieldClassFromTheFuture", UnknownDatabaseField),
        ]
    )
    def test_unknown_hogql_field_class_degrades_gracefully(
        self, _name: str, hogql_class: str, expected_type: type[DatabaseField]
    ) -> None:
        saved_query = DataWarehouseSavedQuery(
            name="my_view",
            query={"query": "SELECT 1 AS id"},
            columns={"id": {"clickhouse": "String", "hogql": hogql_class, "valid": True}},
            column_order=["id"],
        )

        fields: dict[str, Any] = saved_query.hogql_definition().fields

        assert type(fields["id"]) is expected_type
