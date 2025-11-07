from freezegun import freeze_time
from unittest import mock

from dateutil import parser

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
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
                team_id=1,
                should_use_incremental_field=False,
                db_incremental_field_last_value=None,
                db_incremental_field_earliest_value=None,
                incremental_field=None,
                incremental_field_type=None,
                job_id="job-id",
                logger=mock.MagicMock(),
            ),
        )

    mock_delete_all_temp_destination_tables.assert_called_once_with(
        dataset_id="dataset-id",
        table_prefix="__posthog_import_schema_id",
        project_id=config.key_file.project_id,
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
        dataset_project_id=None,
        private_key=config.key_file.private_key,
        private_key_id=config.key_file.private_key_id,
        client_email=config.key_file.client_email,
        token_uri=config.key_file.token_uri,
        table_name="schema",
        should_use_incremental_field=False,
        logger=mock.ANY,
        bq_destination_table_id=f"project-id.dataset-id.__posthog_import_schema_id_job_id_{str(parser.parse("2025-01-01T12:00:00.000Z").timestamp()).replace('.', '')}",
        incremental_field=None,
        incremental_field_type=None,
        db_incremental_field_last_value=None,
    )

    mock_delete_table.assert_called_once_with(
        table_id=f"project-id.dataset-id.__posthog_import_schema_id_job_id_{str(parser.parse("2025-01-01T12:00:00.000Z").timestamp()).replace('.', '')}",
        project_id=config.key_file.project_id,
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
                team_id=1,
                should_use_incremental_field=False,
                db_incremental_field_last_value=None,
                db_incremental_field_earliest_value=None,
                incremental_field=None,
                incremental_field_type=None,
                job_id="job-id",
                logger=mock.MagicMock(),
            ),
        )

    mock_delete_all_temp_destination_tables.assert_called_once_with(
        dataset_id="dataset-id",
        table_prefix="__posthog_import_schema_id",
        project_id=config.key_file.project_id,
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
        dataset_project_id="other-project-id",
        private_key=config.key_file.private_key,
        private_key_id=config.key_file.private_key_id,
        client_email=config.key_file.client_email,
        token_uri=config.key_file.token_uri,
        table_name="schema",
        should_use_incremental_field=False,
        logger=mock.ANY,
        bq_destination_table_id=f"project-id.dataset-id.__posthog_import_schema_id_job_id_{str(parser.parse("2025-01-01T12:00:00.000Z").timestamp()).replace('.', '')}",
        incremental_field=None,
        incremental_field_type=None,
        db_incremental_field_last_value=None,
    )

    mock_delete_table.assert_called_once_with(
        table_id=f"project-id.dataset-id.__posthog_import_schema_id_job_id_{str(parser.parse("2025-01-01T12:00:00.000Z").timestamp()).replace('.', '')}",
        project_id=config.key_file.project_id,
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
                team_id=1,
                should_use_incremental_field=False,
                db_incremental_field_last_value=None,
                db_incremental_field_earliest_value=None,
                incremental_field=None,
                incremental_field_type=None,
                job_id="job-id",
                logger=mock.MagicMock(),
            ),
        )

    mock_delete_all_temp_destination_tables.assert_called_once_with(
        dataset_id="some-other-dataset-id",
        table_prefix="__posthog_import_schema_id",
        project_id=config.key_file.project_id,
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
        dataset_project_id=None,
        private_key=config.key_file.private_key,
        private_key_id=config.key_file.private_key_id,
        client_email=config.key_file.client_email,
        token_uri=config.key_file.token_uri,
        table_name="schema",
        should_use_incremental_field=False,
        logger=mock.ANY,
        bq_destination_table_id=f"project-id.some-other-dataset-id.__posthog_import_schema_id_job_id_{str(parser.parse("2025-01-01T12:00:00.000Z").timestamp()).replace('.', '')}",
        incremental_field=None,
        incremental_field_type=None,
        db_incremental_field_last_value=None,
    )

    mock_delete_table.assert_called_once_with(
        table_id=f"project-id.some-other-dataset-id.__posthog_import_schema_id_job_id_{str(parser.parse("2025-01-01T12:00:00.000Z").timestamp()).replace('.', '')}",
        project_id=config.key_file.project_id,
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
                team_id=1,
                should_use_incremental_field=False,
                db_incremental_field_last_value=None,
                db_incremental_field_earliest_value=None,
                incremental_field=None,
                incremental_field_type=None,
                job_id="job-id",
                logger=mock.MagicMock(),
            ),
        )

    mock_delete_all_temp_destination_tables.assert_called_once_with(
        dataset_id="some-other-dataset-id",
        table_prefix="__posthog_import_schema_id",
        project_id=config.key_file.project_id,
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
        dataset_project_id="other-project-id",
        private_key=config.key_file.private_key,
        private_key_id=config.key_file.private_key_id,
        client_email=config.key_file.client_email,
        token_uri=config.key_file.token_uri,
        table_name="schema",
        should_use_incremental_field=False,
        logger=mock.ANY,
        bq_destination_table_id=f"project-id.some-other-dataset-id.__posthog_import_schema_id_job_id_{str(parser.parse("2025-01-01T12:00:00.000Z").timestamp()).replace('.', '')}",
        incremental_field=None,
        incremental_field_type=None,
        db_incremental_field_last_value=None,
    )

    mock_delete_table.assert_called_once_with(
        table_id=f"project-id.some-other-dataset-id.__posthog_import_schema_id_job_id_{str(parser.parse("2025-01-01T12:00:00.000Z").timestamp()).replace('.', '')}",
        project_id=config.key_file.project_id,
        private_key=config.key_file.private_key,
        private_key_id=config.key_file.private_key_id,
        client_email=config.key_file.client_email,
        token_uri=config.key_file.token_uri,
    )
