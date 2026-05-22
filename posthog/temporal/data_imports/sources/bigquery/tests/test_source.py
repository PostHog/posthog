from freezegun import freeze_time
from unittest import mock

from dateutil import parser

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from posthog.temporal.data_imports.sources.bigquery.bigquery import BigQueryImplementation
from posthog.temporal.data_imports.sources.bigquery.source import BigQuerySource
from posthog.temporal.data_imports.sources.generated_configs import (
    BigQueryDatasetProjectConfig,
    BigQueryKeyFileConfig,
    BigQuerySourceConfig,
    BigQueryTemporaryDatasetConfig,
)


def _make_inputs(**overrides) -> SourceInputs:
    defaults: dict = {
        "schema_name": "schema",
        "schema_id": "schema-id",
        "source_id": "source-id",
        "team_id": 1,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-id",
        "logger": mock.MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


def test_get_implementation_returns_singleton():
    source = BigQuerySource()
    impl = source.get_implementation
    assert isinstance(impl, BigQueryImplementation)
    # Returned twice — must be the same module-level singleton.
    assert BigQuerySource().get_implementation is impl


def test_bigquery_get_schemas():
    with (
        mock.patch.object(BigQueryImplementation, "connect", return_value=mock.MagicMock()),
        mock.patch.object(BigQueryImplementation, "get_columns", return_value={"table": [("c", "STRING", True)]}),
        mock.patch.object(BigQueryImplementation, "get_primary_keys", return_value={}),
        mock.patch.object(BigQueryImplementation, "get_leading_index_columns", return_value={}),
    ):
        source_cls = BigQuerySource()
        schemas = source_cls.get_schemas(mock.ANY, 1)
        assert len(schemas) == 1
        assert schemas[0].name == "table"


def test_bigquery_get_columns_filters_existing_destination_tables():
    """`get_columns` strips `__posthog_import_*` tables before returning."""
    fake_client = mock.MagicMock()
    fake_row_keep = mock.MagicMock(table_name="table", column_name="c", data_type="STRING", is_nullable="NO")
    fake_row_skip = mock.MagicMock(
        table_name="__posthog_import_0000_0000", column_name="c", data_type="STRING", is_nullable="NO"
    )
    fake_client.query.return_value.result.return_value = [fake_row_keep, fake_row_skip]

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
    columns = BigQueryImplementation().get_columns(fake_client, config, names=None)
    assert list(columns.keys()) == ["table"]


def _run_source_for_pipeline(config: BigQuerySourceConfig, inputs: SourceInputs):
    with (
        freeze_time("2025-01-01T12:00:00.000Z"),
        mock.patch(
            "posthog.temporal.data_imports.sources.bigquery.bigquery.delete_all_temp_destination_tables",
        ) as mock_delete_all_temp_destination_tables,
        mock.patch.object(
            BigQueryImplementation, "_build_source_response", return_value=mock.MagicMock()
        ) as mock_build_source_response,
        mock.patch(
            "posthog.temporal.data_imports.sources.bigquery.bigquery.delete_table",
        ) as mock_delete_table,
    ):
        BigQuerySource().source_for_pipeline(config, inputs)
    return mock_delete_all_temp_destination_tables, mock_build_source_response, mock_delete_table


def test_bigquery_destination_table_default():
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

    mock_delete_all, mock_build, mock_delete = _run_source_for_pipeline(config, _make_inputs())

    expected_table_id = (
        f"project-id.dataset-id.__posthog_import_schema_id_job_id_"
        f"{str(parser.parse('2025-01-01T12:00:00.000Z').timestamp()).replace('.', '')}"
    )

    mock_delete_all.assert_called_once_with(
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

    assert mock_build.call_count == 1
    _, call_kwargs = mock_build.call_args
    assert call_kwargs["region"] is None
    assert call_kwargs["dataset_project_id"] is None
    assert call_kwargs["bq_destination_table_id"] == expected_table_id

    mock_delete.assert_called_once_with(
        table_id=expected_table_id,
        project_id=config.key_file.project_id,
        location=None,
        private_key=config.key_file.private_key,
        private_key_id=config.key_file.private_key_id,
        client_email=config.key_file.client_email,
        token_uri=config.key_file.token_uri,
    )


def test_bigquery_destination_table_with_dataset_project_set():
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

    mock_delete_all, mock_build, mock_delete = _run_source_for_pipeline(config, _make_inputs())

    expected_table_id = (
        f"project-id.dataset-id.__posthog_import_schema_id_job_id_"
        f"{str(parser.parse('2025-01-01T12:00:00.000Z').timestamp()).replace('.', '')}"
    )

    mock_delete_all.assert_called_once_with(
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

    _, call_kwargs = mock_build.call_args
    assert call_kwargs["dataset_project_id"] == "other-project-id"
    assert call_kwargs["bq_destination_table_id"] == expected_table_id

    mock_delete.assert_called_once_with(
        table_id=expected_table_id,
        project_id=config.key_file.project_id,
        location=None,
        private_key=config.key_file.private_key,
        private_key_id=config.key_file.private_key_id,
        client_email=config.key_file.client_email,
        token_uri=config.key_file.token_uri,
    )


def test_bigquery_destination_table_with_temporary_dataset_set():
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

    mock_delete_all, mock_build, mock_delete = _run_source_for_pipeline(config, _make_inputs())

    expected_table_id = (
        f"project-id.some-other-dataset-id.__posthog_import_schema_id_job_id_"
        f"{str(parser.parse('2025-01-01T12:00:00.000Z').timestamp()).replace('.', '')}"
    )

    mock_delete_all.assert_called_once_with(
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

    _, call_kwargs = mock_build.call_args
    assert call_kwargs["bq_destination_table_id"] == expected_table_id

    mock_delete.assert_called_once_with(
        table_id=expected_table_id,
        project_id=config.key_file.project_id,
        location=None,
        private_key=config.key_file.private_key,
        private_key_id=config.key_file.private_key_id,
        client_email=config.key_file.client_email,
        token_uri=config.key_file.token_uri,
    )


def test_bigquery_destination_table_with_both_temporary_dataset_and_dataset_project_set():
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

    mock_delete_all, mock_build, mock_delete = _run_source_for_pipeline(config, _make_inputs())

    expected_table_id = (
        f"project-id.some-other-dataset-id.__posthog_import_schema_id_job_id_"
        f"{str(parser.parse('2025-01-01T12:00:00.000Z').timestamp()).replace('.', '')}"
    )

    mock_delete_all.assert_called_once_with(
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

    _, call_kwargs = mock_build.call_args
    assert call_kwargs["dataset_project_id"] == "other-project-id"
    assert call_kwargs["bq_destination_table_id"] == expected_table_id

    mock_delete.assert_called_once_with(
        table_id=expected_table_id,
        project_id=config.key_file.project_id,
        location=None,
        private_key=config.key_file.private_key,
        private_key_id=config.key_file.private_key_id,
        client_email=config.key_file.client_email,
        token_uri=config.key_file.token_uri,
    )
