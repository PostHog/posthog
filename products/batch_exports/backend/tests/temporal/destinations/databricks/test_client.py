from unittest.mock import patch

from products.batch_exports.backend.temporal.destinations.databricks_batch_export import DatabricksClient


async def test_amerge_mutable_tables_with_schema_evolution():
    """Test that we construct the correct SQL for merging with schema evolution.

    We mock the execute_async_query method to assert that the correct SQL is constructed.
    """
    with patch(
        "products.batch_exports.backend.temporal.destinations.databricks_batch_export.DatabricksClient.execute_async_query"
    ) as mock_execute_async_query:
        client = DatabricksClient(
            server_hostname="test",
            http_path="test",
            client_id="test",
            client_secret="test",
            catalog="test",
            schema="test",
        )
        merge_key = ["team_id", "distinct_id"]
        update_key = ["person_version", "person_distinct_id_version"]
        await client.amerge_mutable_tables(
            target_table="test_target",
            source_table="test_source",
            merge_key=merge_key,
            update_key=update_key,
            fields=[
                ("team_id", "INTEGER"),
                ("distinct_id", "STRING"),
                ("person_version", "INTEGER"),
                ("person_distinct_id_version", "INTEGER"),
                ("properties", "VARIANT"),
            ],
            with_schema_evolution=True,
        )
        mock_execute_async_query.assert_called_once_with(
            """
            MERGE WITH SCHEMA EVOLUTION INTO `test_target` AS target
            USING `test_source` AS source
            ON target.`team_id` = source.`team_id` AND target.`distinct_id` = source.`distinct_id`
            WHEN MATCHED AND (target.`person_version` < source.`person_version` OR target.`person_distinct_id_version` < source.`person_distinct_id_version`) THEN
                UPDATE SET *
            WHEN NOT MATCHED THEN
                INSERT *
            """,
            fetch_results=False,
        )


async def test_amerge_mutable_tables_without_schema_evolution():
    """Test that we construct the correct SQL for merging without schema evolution.

    We mock execute_async_query to assert that the correct SQL is constructed.
    We also mock get_table_columns to return the column names of the target table.
    """
    with (
        patch(
            "products.batch_exports.backend.temporal.destinations.databricks_batch_export.DatabricksClient.execute_async_query"
        ) as mock_execute_async_query,
        patch(
            "products.batch_exports.backend.temporal.destinations.databricks_batch_export.DatabricksClient.aget_table_columns",
            return_value=["team_id", "distinct_id", "person_version", "person_distinct_id_version", "properties"],
        ),
    ):
        client = DatabricksClient(
            server_hostname="test",
            http_path="test",
            client_id="test",
            client_secret="test",
            catalog="test",
            schema="test",
        )
        merge_key = ["team_id", "distinct_id"]
        update_key = ["person_version", "person_distinct_id_version"]
        await client.amerge_mutable_tables(
            target_table="test_target",
            source_table="test_source",
            merge_key=merge_key,
            update_key=update_key,
            fields=[
                ("team_id", "INTEGER"),
                ("distinct_id", "STRING"),
                ("person_version", "INTEGER"),
                ("person_distinct_id_version", "INTEGER"),
                ("properties", "VARIANT"),
            ],
            with_schema_evolution=False,
        )
        actual_query = mock_execute_async_query.call_args[0][0]
        expected_query = """
            MERGE INTO `test_target` AS target
            USING `test_source` AS source
            ON target.`team_id` = source.`team_id` AND target.`distinct_id` = source.`distinct_id`
            WHEN MATCHED AND (target.`person_version` < source.`person_version` OR target.`person_distinct_id_version` < source.`person_distinct_id_version`) THEN
                UPDATE SET
                    target.`team_id` = source.`team_id`, target.`distinct_id` = source.`distinct_id`, target.`person_version` = source.`person_version`, target.`person_distinct_id_version` = source.`person_distinct_id_version`, target.`properties` = source.`properties`
            WHEN NOT MATCHED THEN
                INSERT (`team_id`, `distinct_id`, `person_version`, `person_distinct_id_version`, `properties`)
                VALUES (source.`team_id`, source.`distinct_id`, source.`person_version`, source.`person_distinct_id_version`, source.`properties`)
            """
    assert actual_query == expected_query


async def test_amerge_mutable_tables_without_schema_evolution_and_target_table_has_less_fields():
    """Test that we construct the correct SQL for merging without schema evolution.

    We mock execute_async_query to assert that the correct SQL is constructed.
    We also mock get_table_columns to return the column names of the target table.

    If the target table is missing some fields, we should only update the fields that are present in the target table.
    In this example, the "new_field" field should be ignored.
    """
    with (
        patch(
            "products.batch_exports.backend.temporal.destinations.databricks_batch_export.DatabricksClient.execute_async_query"
        ) as mock_execute_async_query,
        patch(
            "products.batch_exports.backend.temporal.destinations.databricks_batch_export.DatabricksClient.aget_table_columns",
            return_value=["team_id", "distinct_id", "person_version", "person_distinct_id_version", "properties"],
        ),
    ):
        client = DatabricksClient(
            server_hostname="test",
            http_path="test",
            client_id="test",
            client_secret="test",
            catalog="test",
            schema="test",
        )
        merge_key = ["team_id", "distinct_id"]
        update_key = ["person_version", "person_distinct_id_version"]
        await client.amerge_mutable_tables(
            target_table="test_target",
            source_table="test_source",
            merge_key=merge_key,
            update_key=update_key,
            fields=[
                ("team_id", "INTEGER"),
                ("distinct_id", "STRING"),
                ("person_version", "INTEGER"),
                ("person_distinct_id_version", "INTEGER"),
                ("properties", "VARIANT"),
                ("new_field", "STRING"),
            ],
            with_schema_evolution=False,
        )
        actual_query = mock_execute_async_query.call_args[0][0]
        expected_query = """
            MERGE INTO `test_target` AS target
            USING `test_source` AS source
            ON target.`team_id` = source.`team_id` AND target.`distinct_id` = source.`distinct_id`
            WHEN MATCHED AND (target.`person_version` < source.`person_version` OR target.`person_distinct_id_version` < source.`person_distinct_id_version`) THEN
                UPDATE SET
                    target.`team_id` = source.`team_id`, target.`distinct_id` = source.`distinct_id`, target.`person_version` = source.`person_version`, target.`person_distinct_id_version` = source.`person_distinct_id_version`, target.`properties` = source.`properties`
            WHEN NOT MATCHED THEN
                INSERT (`team_id`, `distinct_id`, `person_version`, `person_distinct_id_version`, `properties`)
                VALUES (source.`team_id`, source.`distinct_id`, source.`person_version`, source.`person_distinct_id_version`, source.`properties`)
            """
    assert actual_query == expected_query
