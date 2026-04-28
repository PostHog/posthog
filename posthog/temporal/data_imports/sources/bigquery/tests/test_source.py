import pytest
from freezegun import freeze_time
from unittest import mock

from dateutil import parser
from google.api_core.exceptions import Forbidden

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from posthog.temporal.data_imports.sources.bigquery import bigquery as bigquery_module
from posthog.temporal.data_imports.sources.bigquery.source import BigQuerySource
from posthog.temporal.data_imports.sources.generated_configs import (
    BigQueryDatasetProjectConfig,
    BigQueryKeyFileConfig,
    BigQuerySourceConfig,
    BigQueryTemporaryDatasetConfig,
)


def test_bigquery_get_schemas():
    with mock.patch(
        "posthog.temporal.data_imports.sources.bigquery.source.get_bigquery_schemas", return_value={"table": []}
    ):
        source_cls = BigQuerySource()
        schemas = source_cls.get_schemas(mock.ANY, 1)
        assert len(schemas) == 1
        assert schemas[0].name == "table"


def test_bigquery_get_schemas_with_existing_destination_tables():
    with mock.patch(
        "posthog.temporal.data_imports.sources.bigquery.source.get_bigquery_schemas",
        return_value={"table": [], "__posthog_import_0000_0000": []},
    ):
        source_cls = BigQuerySource()
        schemas = source_cls.get_schemas(mock.ANY, 1)
        assert len(schemas) == 1
        assert schemas[0].name == "table"


@pytest.mark.parametrize(
    "dataset_project,expected_project_in_message,expects_cross_project_hint",
    [
        (None, "service-account-project", True),
        (
            BigQueryDatasetProjectConfig(dataset_project_id="other-project", enabled=True),
            "other-project",
            False,
        ),
    ],
)
def test_bigquery_get_schemas_raises_actionable_error_on_forbidden(
    dataset_project, expected_project_in_message, expects_cross_project_hint
):
    """When BigQuery returns 403 on INFORMATION_SCHEMA.COLUMNS, surface a clear error.

    Previously this swallowed the Forbidden and returned an empty dict, leaving the
    source wizard with "No schemas found" and no way for the user to recover.
    """
    config = BigQuerySourceConfig(
        key_file=BigQueryKeyFileConfig(
            project_id="service-account-project",
            private_key="private-key",
            private_key_id="private-key-id",
            client_email="client-email",
            token_uri="token-uri",
        ),
        dataset_id="my-dataset",
        dataset_project=dataset_project,
        temporary_dataset=None,
    )

    mock_query = mock.MagicMock()
    mock_query.result.side_effect = Forbidden("permission denied")
    mock_client = mock.MagicMock()
    mock_client.query.return_value = mock_query

    with mock.patch.object(bigquery_module, "bigquery_client") as mock_client_cm:
        mock_client_cm.return_value.__enter__.return_value = mock_client

        with pytest.raises(PermissionError) as exc_info:
            bigquery_module.get_schemas(config)

    message = str(exc_info.value)
    assert "INFORMATION_SCHEMA.COLUMNS" in message
    assert "my-dataset" in message
    assert expected_project_in_message in message
    assert ("Use a different project for the dataset" in message) is expects_cross_project_hint
    # Wrapped exception preserved for debugging.
    assert isinstance(exc_info.value.__cause__, Forbidden)


def test_bigquery_get_schemas_returns_empty_dict_when_dataset_has_no_tables():
    """An empty INFORMATION_SCHEMA.COLUMNS result should still be treated as success."""
    config = BigQuerySourceConfig(
        key_file=BigQueryKeyFileConfig(
            project_id="project",
            private_key="private-key",
            private_key_id="private-key-id",
            client_email="client-email",
            token_uri="token-uri",
        ),
        dataset_id="empty-dataset",
        dataset_project=None,
        temporary_dataset=None,
    )

    mock_query = mock.MagicMock()
    mock_query.result.return_value = iter([])
    mock_client = mock.MagicMock()
    mock_client.query.return_value = mock_query

    with mock.patch.object(bigquery_module, "bigquery_client") as mock_client_cm:
        mock_client_cm.return_value.__enter__.return_value = mock_client

        result = bigquery_module.get_schemas(config)

    assert result == {}


def test_bigquery_destination_table_default():
    source_cls = BigQuerySource()
    config = BigQuerySourceConfig(
        key_file=BigQueryKeyFileConfig(
            project_id="project-id",
            private_key="private-key",
            private_key_id="private-key-id",
            client_email="client-email",
            token_uri="token-uri",
        ),
        dataset_id="dataset-id",
        dataset_project=None,
        temporary_dataset=None,
    )

    with (
        freeze_time("2025-01-01T12:00:00.000Z"),
        mock.patch(
            "posthog.temporal.data_imports.sources.bigquery.source.delete_all_temp_destination_tables",
        ) as mock_delete_all_temp_destination_tables,
        mock.patch(
            "posthog.temporal.data_imports.sources.bigquery.source.bigquery_source",
        ) as mock_bigquery_source,
        mock.patch(
            "posthog.temporal.data_imports.sources.bigquery.source.delete_table",
        ) as mock_delete_table,
    ):
        source_cls.source_for_pipeline(
            config,
            SourceInputs(
                schema_name="schema",
                schema_id="schema-id",
                source_id="source-id",
                team_id=1,
                should_use_incremental_field=False,
                db_incremental_field_last_value=None,
                db_incremental_field_earliest_value=None,
                incremental_field=None,
                incremental_field_type=None,
                job_id="job-id",
                logger=mock.MagicMock(),
                reset_pipeline=False,
            ),
        )

    mock_delete_all_temp_destination_tables.assert_called_once_with(
        dataset_id="dataset-id",
        table_prefix="__posthog_import_schema_id",
        project_id=config.key_file.project_id,
        location=None,
        dataset_project_id=None,
        private_key=config.key_file.private_key,
        private_key_id=config.key_file.private_key_id,
        client_email=config.key_file.client_email,
        token_uri=config.key_file.token_uri,
        logger=mock.ANY,
    )

    mock_bigquery_source.assert_called_once_with(
        dataset_id=config.dataset_id,
        project_id=config.key_file.project_id,
        location=None,
        dataset_project_id=None,
        private_key=config.key_file.private_key,
        private_key_id=config.key_file.private_key_id,
        client_email=config.key_file.client_email,
        token_uri=config.key_file.token_uri,
        table_name="schema",
        should_use_incremental_field=False,
        logger=mock.ANY,
        bq_destination_table_id=f"project-id.dataset-id.__posthog_import_schema_id_job_id_{str(parser.parse('2025-01-01T12:00:00.000Z').timestamp()).replace('.', '')}",
        incremental_field=None,
        incremental_field_type=None,
        db_incremental_field_last_value=None,
    )

    mock_delete_table.assert_called_once_with(
        table_id=f"project-id.dataset-id.__posthog_import_schema_id_job_id_{str(parser.parse('2025-01-01T12:00:00.000Z').timestamp()).replace('.', '')}",
        project_id=config.key_file.project_id,
        location=None,
        private_key=config.key_file.private_key,
        private_key_id=config.key_file.private_key_id,
        client_email=config.key_file.client_email,
        token_uri=config.key_file.token_uri,
    )


def test_bigquery_destination_table_with_dataset_project_set():
    source_cls = BigQuerySource()
    config = BigQuerySourceConfig(
        key_file=BigQueryKeyFileConfig(
            project_id="project-id",
            private_key="private-key",
            private_key_id="private-key-id",
            client_email="client-email",
            token_uri="token-uri",
        ),
        dataset_id="dataset-id",
        dataset_project=BigQueryDatasetProjectConfig(
            dataset_project_id="other-project-id",
            enabled=True,
        ),
        temporary_dataset=None,
    )

    with (
        freeze_time("2025-01-01T12:00:00.000Z"),
        mock.patch(
            "posthog.temporal.data_imports.sources.bigquery.source.delete_all_temp_destination_tables",
        ) as mock_delete_all_temp_destination_tables,
        mock.patch(
            "posthog.temporal.data_imports.sources.bigquery.source.bigquery_source",
        ) as mock_bigquery_source,
        mock.patch(
            "posthog.temporal.data_imports.sources.bigquery.source.delete_table",
        ) as mock_delete_table,
    ):
        source_cls.source_for_pipeline(
            config,
            SourceInputs(
                schema_name="schema",
                schema_id="schema-id",
                source_id="source-id",
                team_id=1,
                should_use_incremental_field=False,
                db_incremental_field_last_value=None,
                db_incremental_field_earliest_value=None,
                incremental_field=None,
                incremental_field_type=None,
                job_id="job-id",
                logger=mock.MagicMock(),
                reset_pipeline=False,
            ),
        )

    mock_delete_all_temp_destination_tables.assert_called_once_with(
        dataset_id="dataset-id",
        table_prefix="__posthog_import_schema_id",
        project_id=config.key_file.project_id,
        location=None,
        dataset_project_id="other-project-id",
        private_key=config.key_file.private_key,
        private_key_id=config.key_file.private_key_id,
        client_email=config.key_file.client_email,
        token_uri=config.key_file.token_uri,
        logger=mock.ANY,
    )

    mock_bigquery_source.assert_called_once_with(
        dataset_id=config.dataset_id,
        project_id=config.key_file.project_id,
        location=None,
        dataset_project_id="other-project-id",
        private_key=config.key_file.private_key,
        private_key_id=config.key_file.private_key_id,
        client_email=config.key_file.client_email,
        token_uri=config.key_file.token_uri,
        table_name="schema",
        should_use_incremental_field=False,
        logger=mock.ANY,
        bq_destination_table_id=f"project-id.dataset-id.__posthog_import_schema_id_job_id_{str(parser.parse('2025-01-01T12:00:00.000Z').timestamp()).replace('.', '')}",
        incremental_field=None,
        incremental_field_type=None,
        db_incremental_field_last_value=None,
    )

    mock_delete_table.assert_called_once_with(
        table_id=f"project-id.dataset-id.__posthog_import_schema_id_job_id_{str(parser.parse('2025-01-01T12:00:00.000Z').timestamp()).replace('.', '')}",
        project_id=config.key_file.project_id,
        location=None,
        private_key=config.key_file.private_key,
        private_key_id=config.key_file.private_key_id,
        client_email=config.key_file.client_email,
        token_uri=config.key_file.token_uri,
    )


def test_bigquery_destination_table_with_temporary_dataset_set():
    source_cls = BigQuerySource()
    config = BigQuerySourceConfig(
        key_file=BigQueryKeyFileConfig(
            project_id="project-id",
            private_key="private-key",
            private_key_id="private-key-id",
            client_email="client-email",
            token_uri="token-uri",
        ),
        dataset_id="dataset-id",
        dataset_project=None,
        temporary_dataset=BigQueryTemporaryDatasetConfig(
            temporary_dataset_id="some-other-dataset-id",
            enabled=True,
        ),
    )

    with (
        freeze_time("2025-01-01T12:00:00.000Z"),
        mock.patch(
            "posthog.temporal.data_imports.sources.bigquery.source.delete_all_temp_destination_tables",
        ) as mock_delete_all_temp_destination_tables,
        mock.patch(
            "posthog.temporal.data_imports.sources.bigquery.source.bigquery_source",
        ) as mock_bigquery_source,
        mock.patch(
            "posthog.temporal.data_imports.sources.bigquery.source.delete_table",
        ) as mock_delete_table,
    ):
        source_cls.source_for_pipeline(
            config,
            SourceInputs(
                schema_name="schema",
                schema_id="schema-id",
                source_id="source-id",
                team_id=1,
                should_use_incremental_field=False,
                db_incremental_field_last_value=None,
                db_incremental_field_earliest_value=None,
                incremental_field=None,
                incremental_field_type=None,
                job_id="job-id",
                logger=mock.MagicMock(),
                reset_pipeline=False,
            ),
        )

    mock_delete_all_temp_destination_tables.assert_called_once_with(
        dataset_id="some-other-dataset-id",
        table_prefix="__posthog_import_schema_id",
        project_id=config.key_file.project_id,
        location=None,
        dataset_project_id=None,
        private_key=config.key_file.private_key,
        private_key_id=config.key_file.private_key_id,
        client_email=config.key_file.client_email,
        token_uri=config.key_file.token_uri,
        logger=mock.ANY,
    )

    mock_bigquery_source.assert_called_once_with(
        dataset_id=config.dataset_id,
        project_id=config.key_file.project_id,
        location=None,
        dataset_project_id=None,
        private_key=config.key_file.private_key,
        private_key_id=config.key_file.private_key_id,
        client_email=config.key_file.client_email,
        token_uri=config.key_file.token_uri,
        table_name="schema",
        should_use_incremental_field=False,
        logger=mock.ANY,
        bq_destination_table_id=f"project-id.some-other-dataset-id.__posthog_import_schema_id_job_id_{str(parser.parse('2025-01-01T12:00:00.000Z').timestamp()).replace('.', '')}",
        incremental_field=None,
        incremental_field_type=None,
        db_incremental_field_last_value=None,
    )

    mock_delete_table.assert_called_once_with(
        table_id=f"project-id.some-other-dataset-id.__posthog_import_schema_id_job_id_{str(parser.parse('2025-01-01T12:00:00.000Z').timestamp()).replace('.', '')}",
        project_id=config.key_file.project_id,
        location=None,
        private_key=config.key_file.private_key,
        private_key_id=config.key_file.private_key_id,
        client_email=config.key_file.client_email,
        token_uri=config.key_file.token_uri,
    )


def test_bigquery_destination_table_with_both_temporary_dataset_and_dataset_project_set():
    source_cls = BigQuerySource()
    config = BigQuerySourceConfig(
        key_file=BigQueryKeyFileConfig(
            project_id="project-id",
            private_key="private-key",
            private_key_id="private-key-id",
            client_email="client-email",
            token_uri="token-uri",
        ),
        dataset_id="dataset-id",
        dataset_project=BigQueryDatasetProjectConfig(
            dataset_project_id="other-project-id",
            enabled=True,
        ),
        temporary_dataset=BigQueryTemporaryDatasetConfig(
            temporary_dataset_id="some-other-dataset-id",
            enabled=True,
        ),
    )

    with (
        freeze_time("2025-01-01T12:00:00.000Z"),
        mock.patch(
            "posthog.temporal.data_imports.sources.bigquery.source.delete_all_temp_destination_tables",
        ) as mock_delete_all_temp_destination_tables,
        mock.patch(
            "posthog.temporal.data_imports.sources.bigquery.source.bigquery_source",
        ) as mock_bigquery_source,
        mock.patch(
            "posthog.temporal.data_imports.sources.bigquery.source.delete_table",
        ) as mock_delete_table,
    ):
        source_cls.source_for_pipeline(
            config,
            SourceInputs(
                schema_name="schema",
                schema_id="schema-id",
                source_id="source-id",
                team_id=1,
                should_use_incremental_field=False,
                db_incremental_field_last_value=None,
                db_incremental_field_earliest_value=None,
                incremental_field=None,
                incremental_field_type=None,
                job_id="job-id",
                logger=mock.MagicMock(),
                reset_pipeline=False,
            ),
        )

    mock_delete_all_temp_destination_tables.assert_called_once_with(
        dataset_id="some-other-dataset-id",
        table_prefix="__posthog_import_schema_id",
        project_id=config.key_file.project_id,
        location=None,
        dataset_project_id="other-project-id",
        private_key=config.key_file.private_key,
        private_key_id=config.key_file.private_key_id,
        client_email=config.key_file.client_email,
        token_uri=config.key_file.token_uri,
        logger=mock.ANY,
    )

    mock_bigquery_source.assert_called_once_with(
        dataset_id=config.dataset_id,
        project_id=config.key_file.project_id,
        location=None,
        dataset_project_id="other-project-id",
        private_key=config.key_file.private_key,
        private_key_id=config.key_file.private_key_id,
        client_email=config.key_file.client_email,
        token_uri=config.key_file.token_uri,
        table_name="schema",
        should_use_incremental_field=False,
        logger=mock.ANY,
        bq_destination_table_id=f"project-id.some-other-dataset-id.__posthog_import_schema_id_job_id_{str(parser.parse('2025-01-01T12:00:00.000Z').timestamp()).replace('.', '')}",
        incremental_field=None,
        incremental_field_type=None,
        db_incremental_field_last_value=None,
    )

    mock_delete_table.assert_called_once_with(
        table_id=f"project-id.some-other-dataset-id.__posthog_import_schema_id_job_id_{str(parser.parse('2025-01-01T12:00:00.000Z').timestamp()).replace('.', '')}",
        project_id=config.key_file.project_id,
        location=None,
        private_key=config.key_file.private_key,
        private_key_id=config.key_file.private_key_id,
        client_email=config.key_file.client_email,
        token_uri=config.key_file.token_uri,
    )
