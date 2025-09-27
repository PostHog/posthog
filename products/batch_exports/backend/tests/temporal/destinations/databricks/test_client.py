import pytest

from products.batch_exports.backend.temporal.destinations.databricks_batch_export import (
    DatabricksClient,
    DatabricksConnectionError,
)


async def test_get_merge_query_with_schema_evolution():
    """Test that we construct the correct SQL for merging with schema evolution."""
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
    merge_query = client._get_merge_query_with_schema_evolution(
        target_table="test_target",
        source_table="test_source",
        merge_key=merge_key,
        update_key=update_key,
    )
    assert (
        merge_query
        == """
        MERGE WITH SCHEMA EVOLUTION INTO `test_target` AS target
        USING `test_source` AS source
        ON target.`team_id` = source.`team_id` AND target.`distinct_id` = source.`distinct_id`
        WHEN MATCHED AND (target.`person_version` < source.`person_version` OR target.`person_distinct_id_version` < source.`person_distinct_id_version`) THEN
            UPDATE SET *
        WHEN NOT MATCHED THEN
            INSERT *
        """
    )


async def test_get_merge_query_without_schema_evolution():
    """Test that we construct the correct SQL for merging without schema evolution."""
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
    merge_query = client._get_merge_query_without_schema_evolution(
        target_table="test_target",
        source_table="test_source",
        merge_key=merge_key,
        update_key=update_key,
        source_table_fields=[
            ("team_id", "INTEGER"),
            ("distinct_id", "STRING"),
            ("person_version", "INTEGER"),
            ("person_distinct_id_version", "INTEGER"),
            ("properties", "VARIANT"),
        ],
        target_table_field_names=[
            "team_id",
            "distinct_id",
            "person_version",
            "person_distinct_id_version",
            "properties",
        ],
    )
    assert (
        merge_query
        == """
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
    )


async def test_get_merge_query_without_schema_evolution_and_target_table_has_less_fields():
    """Test that we construct the correct SQL for merging without schema evolution and the target table has less
    fields.

    In this example, the "new_field" field should be ignored.
    """
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
    merge_query = client._get_merge_query_without_schema_evolution(
        target_table="test_target",
        source_table="test_source",
        merge_key=merge_key,
        update_key=update_key,
        source_table_fields=[
            ("team_id", "INTEGER"),
            ("distinct_id", "STRING"),
            ("person_version", "INTEGER"),
            ("person_distinct_id_version", "INTEGER"),
            ("properties", "VARIANT"),
            ("new_field", "STRING"),
        ],
        target_table_field_names=[
            "team_id",
            "distinct_id",
            "person_version",
            "person_distinct_id_version",
            "properties",
        ],
    )
    assert (
        merge_query
        == """
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
    )


async def test_get_copy_into_table_from_volume_query():
    client = DatabricksClient(
        server_hostname="test",
        http_path="test",
        client_id="test",
        client_secret="test",
        catalog="test",
        schema="test",
    )
    fields = [
        ("uuid", "STRING"),
        ("event", "STRING"),
        ("properties", "VARIANT"),
        ("distinct_id", "STRING"),
        ("team_id", "BIGINT"),
        ("timestamp", "TIMESTAMP"),
        ("databricks_ingested_timestamp", "TIMESTAMP"),
    ]
    query = client._get_copy_into_table_from_volume_query(
        table_name="test_table",
        volume_path="/Volumes/my_volume/path/file.parquet",
        fields=fields,
    )
    assert (
        query
        == """
        COPY INTO `test_table`
        FROM (
            SELECT `uuid`, `event`, PARSE_JSON(`properties`) as `properties`, `distinct_id`, CAST(`team_id` as BIGINT) as `team_id`, `timestamp`, `databricks_ingested_timestamp` FROM '/Volumes/my_volume/path/file.parquet'
        )
        FILEFORMAT = PARQUET
        """
    )


async def test_connect_when_invalid_host():
    """Test that we raise an error when the host is invalid."""
    client = DatabricksClient(
        server_hostname="invalid",
        http_path="test",
        client_id="test",
        client_secret="test",
        catalog="test",
        schema="test",
    )
    with pytest.raises(
        DatabricksConnectionError,
        match="Failed to connect to Databricks. Please check that the server_hostname and http_path are valid.",
    ):
        async with client.connect():
            pass
