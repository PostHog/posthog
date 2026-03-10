import pyarrow as pa

from posthog.temporal.data_imports.pipelines.pipeline.hogql_schema import HogQLSchema


class TestHogQLSchema:
    def test_json_detection_with_json_values(self):
        """Test that JSON columns are detected when data contains JSON strings."""
        table = pa.table(
            {
                "id": [1, 2, 3],
                "address": ['{"city": "NYC"}', '{"city": "LA"}', '{"city": "SF"}'],
            }
        )

        schema = HogQLSchema()
        schema.add_pyarrow_table(table)

        assert schema.to_hogql_types() == {
            "id": "IntegerDatabaseField",
            "address": "StringJSONDatabaseField",
        }

    def test_json_detection_with_null_values(self):
        """Test that columns with all null values default to StringDatabaseField."""
        table = pa.table(
            {
                "id": [1, 2, 3],
                "address": [None, None, None],
            },
            schema=pa.schema([("id", pa.int64()), ("address", pa.string())]),
        )

        schema = HogQLSchema()
        schema.add_pyarrow_table(table)

        assert schema.to_hogql_types() == {
            "id": "IntegerDatabaseField",
            "address": "StringDatabaseField",
        }

    def test_preserves_existing_json_type_with_null_values(self):
        """Test that existing JSON types are preserved even when new data has all null values.

        This is the fix for the bug where incremental syncs with all NULL values
        would change JSON columns to String.
        """
        # Create existing schema with JSON type
        existing_schema = {
            "id": "IntegerDatabaseField",
            "address": "StringJSONDatabaseField",
        }

        # New data with all null values for address
        table = pa.table(
            {
                "id": [4, 5, 6],
                "address": [None, None, None],
            },
            schema=pa.schema([("id", pa.int64()), ("address", pa.string())]),
        )

        schema = HogQLSchema(existing_schema=existing_schema)
        schema.add_pyarrow_table(table)

        # Should preserve the JSON type from existing schema
        assert schema.to_hogql_types() == {
            "id": "IntegerDatabaseField",
            "address": "StringJSONDatabaseField",
        }

    def test_preserves_existing_types_for_all_columns(self):
        """Test that all existing types are preserved when processing new data."""
        existing_schema = {
            "id": "IntegerDatabaseField",
            "name": "StringDatabaseField",
            "metadata": "StringJSONDatabaseField",
            "created_at": "DateTimeDatabaseField",
        }

        # New data with some null values
        table = pa.table(
            {
                "id": [7, 8],
                "name": ["Alice", None],
                "metadata": [None, '{"key": "value"}'],
                "created_at": [None, None],
            },
            schema=pa.schema(
                [
                    ("id", pa.int64()),
                    ("name", pa.string()),
                    ("metadata", pa.string()),
                    ("created_at", pa.timestamp("us")),
                ]
            ),
        )

        schema = HogQLSchema(existing_schema=existing_schema)
        schema.add_pyarrow_table(table)

        # All types should be preserved
        assert schema.to_hogql_types() == existing_schema

    def test_adds_new_columns_not_in_existing_schema(self):
        """Test that new columns are added with correct types."""
        existing_schema = {
            "id": "IntegerDatabaseField",
            "name": "StringDatabaseField",
        }

        table = pa.table(
            {
                "id": [1, 2],
                "name": ["Alice", "Bob"],
                "email": ["alice@example.com", "bob@example.com"],
                "metadata": ['{"key": "value"}', '{"key": "value2"}'],
            }
        )

        schema = HogQLSchema(existing_schema=existing_schema)
        schema.add_pyarrow_table(table)

        result = schema.to_hogql_types()
        # Existing columns preserved
        assert result["id"] == "IntegerDatabaseField"
        assert result["name"] == "StringDatabaseField"
        # New columns added
        assert result["email"] == "StringDatabaseField"
        assert result["metadata"] == "StringJSONDatabaseField"

    def test_handles_none_existing_schema(self):
        """Test that passing None for existing_schema works like default constructor."""
        table = pa.table(
            {
                "id": [1, 2],
                "data": ['{"key": "value"}', '{"key": "value2"}'],
            }
        )

        schema = HogQLSchema(existing_schema=None)
        schema.add_pyarrow_table(table)

        assert schema.to_hogql_types() == {
            "id": "IntegerDatabaseField",
            "data": "StringJSONDatabaseField",
        }

    def test_handles_empty_existing_schema(self):
        """Test that passing empty dict for existing_schema works."""
        table = pa.table(
            {
                "id": [1, 2],
                "data": ['{"key": "value"}', '{"key": "value2"}'],
            }
        )

        schema = HogQLSchema(existing_schema={})
        schema.add_pyarrow_table(table)

        assert schema.to_hogql_types() == {
            "id": "IntegerDatabaseField",
            "data": "StringJSONDatabaseField",
        }

    def test_preserves_json_type_with_non_json_string(self):
        """Test that existing JSON types are preserved even with non-JSON string values.

        This ensures that once a column is detected as JSON, it stays JSON even if
        later batches have plain strings or nulls.
        """
        existing_schema = {
            "id": "IntegerDatabaseField",
            "address": "StringJSONDatabaseField",
        }

        # New data with non-JSON string for address
        table = pa.table(
            {
                "id": [4, 5, 6],
                "address": ["plain string", "another string", None],
            }
        )

        schema = HogQLSchema(existing_schema=existing_schema)
        schema.add_pyarrow_table(table)

        # Should still preserve the JSON type
        assert schema.to_hogql_types() == {
            "id": "IntegerDatabaseField",
            "address": "StringJSONDatabaseField",
        }

    def test_uses_postgres_type_metadata_for_json(self):
        """Test that Postgres schema metadata is used to detect JSON types."""
        # Postgres type metadata from schema discovery
        postgres_type_map = {"id": "integer", "address": "json", "metadata": "jsonb"}

        # Data with all null JSON columns
        table = pa.table(
            {
                "id": [1, 2, 3],
                "address": [None, None, None],
                "metadata": [None, None, None],
            },
            schema=pa.schema([("id", pa.int64()), ("address", pa.string()), ("metadata", pa.string())]),
        )

        schema = HogQLSchema(postgres_type_map=postgres_type_map)
        schema.add_pyarrow_table(table)

        # Should use Postgres metadata, not data inspection
        assert schema.to_hogql_types() == {
            "id": "IntegerDatabaseField",
            "address": "StringJSONDatabaseField",
            "metadata": "StringJSONDatabaseField",
        }

    def test_postgres_type_metadata_takes_precedence(self):
        """Test that Postgres metadata takes precedence over data inspection."""
        postgres_type_map = {"id": "integer", "data": "json"}

        # Data that looks like plain string, not JSON
        table = pa.table(
            {
                "id": [1, 2],
                "data": ["plain string", "another string"],
            }
        )

        schema = HogQLSchema(postgres_type_map=postgres_type_map)
        schema.add_pyarrow_table(table)

        # Should use Postgres metadata
        assert schema.to_hogql_types() == {
            "id": "IntegerDatabaseField",
            "data": "StringJSONDatabaseField",
        }

    def test_postgres_type_metadata_various_types(self):
        """Test Postgres type mapping for various data types."""
        postgres_type_map = {
            "id": "bigint",
            "amount": "numeric",
            "price": "real",
            "active": "boolean",
            "created": "timestamp",
            "birth_date": "date",
            "name": "text",
            "config": "jsonb",
        }

        table = pa.table(
            {
                "id": [1],
                "amount": [100.5],
                "price": [19.99],
                "active": [True],
                "created": [None],
                "birth_date": [None],
                "name": ["Alice"],
                "config": [None],
            },
            schema=pa.schema(
                [
                    ("id", pa.int64()),
                    ("amount", pa.float64()),
                    ("price", pa.float32()),
                    ("active", pa.bool_()),
                    ("created", pa.timestamp("us")),
                    ("birth_date", pa.date32()),
                    ("name", pa.string()),
                    ("config", pa.string()),
                ]
            ),
        )

        schema = HogQLSchema(postgres_type_map=postgres_type_map)
        schema.add_pyarrow_table(table)

        assert schema.to_hogql_types() == {
            "id": "IntegerDatabaseField",
            "amount": "FloatDatabaseField",
            "price": "FloatDatabaseField",
            "active": "BooleanDatabaseField",
            "created": "DateTimeDatabaseField",
            "birth_date": "DateDatabaseField",
            "name": "StringDatabaseField",
            "config": "StringJSONDatabaseField",
        }

    def test_fallback_to_data_inspection_without_postgres_metadata(self):
        """Test that data inspection still works when no Postgres metadata available."""
        # No postgres_type_map provided
        table = pa.table(
            {
                "id": [1, 2],
                "data": ['{"key": "value"}', '{"key": "value2"}'],
            }
        )

        schema = HogQLSchema()
        schema.add_pyarrow_table(table)

        # Should fall back to data inspection
        assert schema.to_hogql_types() == {
            "id": "IntegerDatabaseField",
            "data": "StringJSONDatabaseField",
        }
