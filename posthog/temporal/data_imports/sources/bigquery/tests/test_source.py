import pytest
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


def _make_config(
    *,
    dataset_project: BigQueryDatasetProjectConfig | None = None,
    temporary_dataset: BigQueryTemporaryDatasetConfig | None = None,
) -> BigQuerySourceConfig:
    return BigQuerySourceConfig(
        key_file=BigQueryKeyFileConfig(
            project_id="project-id",
            private_key="private-key",
            private_key_id="private-key-id",
            client_email="client-email",
            token_uri="token-uri",
        ),
        dataset_id="dataset-id",
        dataset_project=dataset_project,
        temporary_dataset=temporary_dataset,
    )


def test_bigquery_get_columns_filters_existing_destination_tables():
    """`get_columns` strips `__posthog_import_*` tables before returning."""
    fake_client = mock.MagicMock()
    fake_row_keep = mock.MagicMock(table_name="table", column_name="c", data_type="STRING", is_nullable="NO")
    fake_row_skip = mock.MagicMock(
        table_name="__posthog_import_0000_0000", column_name="c", data_type="STRING", is_nullable="NO"
    )
    fake_client.query.return_value.result.return_value = [fake_row_keep, fake_row_skip]

    columns = BigQueryImplementation().get_columns(fake_client, _make_config(), names=None)
    assert list(columns.keys()) == ["table"]


@pytest.mark.parametrize(
    "dataset_project,temporary_dataset,expected_dataset_project_id,expected_destination_dataset_id",
    [
        # default — no dataset_project, no temporary_dataset
        (None, None, None, "dataset-id"),
        # dataset_project enabled — propagated through both delete_all and _build_source_response
        (
            BigQueryDatasetProjectConfig(dataset_project_id="other-project-id", enabled=True),
            None,
            "other-project-id",
            "dataset-id",
        ),
        # temporary_dataset enabled — overrides destination_table_dataset_id
        (
            None,
            BigQueryTemporaryDatasetConfig(temporary_dataset_id="some-other-dataset-id", enabled=True),
            None,
            "some-other-dataset-id",
        ),
        # both set — temporary_dataset wins for destination, dataset_project still resolved
        (
            BigQueryDatasetProjectConfig(dataset_project_id="other-project-id", enabled=True),
            BigQueryTemporaryDatasetConfig(temporary_dataset_id="some-other-dataset-id", enabled=True),
            "other-project-id",
            "some-other-dataset-id",
        ),
    ],
)
def test_bigquery_build_pipeline_resolves_dataset_routing(
    dataset_project, temporary_dataset, expected_dataset_project_id, expected_destination_dataset_id
):
    config = _make_config(dataset_project=dataset_project, temporary_dataset=temporary_dataset)
    expected_table_id = (
        f"project-id.{expected_destination_dataset_id}.__posthog_import_schema_id_job_id_"
        f"{str(parser.parse('2025-01-01T12:00:00.000Z').timestamp()).replace('.', '')}"
    )

    with (
        freeze_time("2025-01-01T12:00:00.000Z"),
        mock.patch(
            "posthog.temporal.data_imports.sources.bigquery.bigquery.delete_all_temp_destination_tables",
        ) as mock_delete_all,
        mock.patch.object(
            BigQueryImplementation, "_build_source_response", return_value=mock.MagicMock()
        ) as mock_build,
        mock.patch(
            "posthog.temporal.data_imports.sources.bigquery.bigquery.delete_table",
        ) as mock_delete,
    ):
        BigQuerySource().source_for_pipeline(config, _make_inputs())

    assert mock_delete_all.call_args.kwargs["dataset_id"] == expected_destination_dataset_id
    assert mock_delete_all.call_args.kwargs["dataset_project_id"] == expected_dataset_project_id
    assert mock_delete_all.call_args.kwargs["table_prefix"] == "__posthog_import_schema_id"

    assert mock_build.call_args.kwargs["dataset_project_id"] == expected_dataset_project_id
    assert mock_build.call_args.kwargs["bq_destination_table_id"] == expected_table_id

    assert mock_delete.call_args.kwargs["table_id"] == expected_table_id
