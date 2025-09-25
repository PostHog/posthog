"""Databricks batch export destination tests using the common test framework."""

import os
import json
import uuid
import typing as t
import datetime as dt
import contextlib
from collections.abc import Callable, Generator

import pytest
import unittest.mock

import numpy as np
from databricks import sql
from databricks.sdk.core import Config, oauth_service_principal
from databricks.sql.exc import ServerOperationError

from posthog.batch_exports.service import (
    BaseBatchExportInputs,
    BatchExportField,
    BatchExportModel,
    DatabricksBatchExportInputs,
)
from posthog.models.team import Team
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.tests.utils.persons import (
    generate_test_person_distinct_id2_in_clickhouse,
    generate_test_persons_in_clickhouse,
)

from products.batch_exports.backend.temporal.destinations.databricks_batch_export import (
    DatabricksBatchExportWorkflow,
    databricks_default_fields,
    insert_into_databricks_activity_from_stage,
)
from products.batch_exports.backend.tests.temporal.destinations.base_destination_tests import (
    BaseDestinationTest,
    CommonWorkflowTests,
    RetryableTestException,
    assert_clickhouse_records_in_destination,
)

REQUIRED_ENV_VARS = (
    "DATABRICKS_SERVER_HOSTNAME",
    "DATABRICKS_HTTP_PATH",
    "DATABRICKS_CLIENT_ID",
    "DATABRICKS_CLIENT_SECRET",
)


pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(
        not all(env_var in os.environ for env_var in REQUIRED_ENV_VARS),
        reason=f"Databricks required env vars are not set: {', '.join(REQUIRED_ENV_VARS)}",
    ),
]


class DatabricksDestinationTest(BaseDestinationTest):
    """Databricks-specific implementation of the base destination test interface."""

    @property
    def destination_type(self) -> str:
        return "Databricks"

    @property
    def workflow_class(self) -> type[PostHogWorkflow]:
        return DatabricksBatchExportWorkflow

    @property
    def main_activity(self) -> Callable:
        return insert_into_databricks_activity_from_stage

    @property
    def batch_export_inputs_class(self) -> type[BaseBatchExportInputs]:
        return DatabricksBatchExportInputs

    @property
    def destination_default_fields(self) -> list[BatchExportField]:
        return databricks_default_fields()

    def get_json_columns(self, inputs: BaseBatchExportInputs) -> list[str]:
        assert isinstance(inputs, DatabricksBatchExportInputs)
        if inputs.use_variant_type is True:
            json_columns = ["properties", "person_properties"]
        else:
            json_columns = []
        return json_columns

    def get_destination_config(self, team_id: int) -> dict:
        """Provide test configuration for Databricks destination.

        NOTE: we're using machine-to-machine OAuth here:
        https://docs.databricks.com/aws/en/dev-tools/python-sql-connector#oauth-machine-to-machine-m2m-authentication
        """
        return {
            "server_hostname": os.getenv("DATABRICKS_SERVER_HOSTNAME"),
            "http_path": os.getenv("DATABRICKS_HTTP_PATH"),
            "client_id": os.getenv("DATABRICKS_CLIENT_ID"),
            "client_secret": os.getenv("DATABRICKS_CLIENT_SECRET"),
            "catalog": os.getenv("DATABRICKS_CATALOG", f"batch_export_tests"),
            # use a hyphen in the schema name to test we handle it correctly
            "schema": os.getenv("DATABRICKS_SCHEMA", f"test_workflow_schema-{team_id}"),
            # use a hyphen in the table name to test we handle it correctly
            "table_name": f"test_workflow_table-{team_id}",
        }

    def get_invalid_destination_config(self) -> tuple[dict, str]:
        """Provide invalid test configuration for Databricks destination."""
        return (
            {
                "server_hostname": "invalid",
                "client_id": "invalid",
                "client_secret": "invalid",
                "http_path": "invalid",
                "catalog": "invalid",
                "schema": "invalid",
                "table_name": "invalid",
            },
            "DatabricksConnectionError: Invalid host: invalid",
        )

    async def get_inserted_records(
        self,
        team_id: int,
        json_columns: list[str],
    ) -> list[dict[str, t.Any]]:
        """Get the inserted records from Databricks."""
        config = self.get_destination_config(team_id)

        with self.cursor(team_id) as cursor:
            cursor.execute(f'USE CATALOG `{config["catalog"]}`')
            cursor.execute(f'USE SCHEMA `{config["schema"]}`')
            cursor.execute(f'SELECT * FROM `{config["table_name"]}`')
            rows = cursor.fetchall()
            assert cursor.description is not None
            columns = {index: metadata[0] for index, metadata in enumerate(cursor.description)}

        # Rows are tuples, so we construct a dictionary using the metadata from cursor.description.
        # We rely on the order of the columns in each row matching the order set in cursor.description.
        # This seems to be the case, at least for now.
        inserted_records = [
            {
                columns[index]: json.loads(row[index])
                if columns[index] in json_columns and row[index] is not None
                # Databricks uses pytz timezones, so we need to convert them to the datetime.UTC timezone
                else row[index].replace(tzinfo=dt.UTC)
                if isinstance(row[index], dt.datetime)
                # convert from numpy arrays to regular lists
                else row[index].tolist()
                if isinstance(row[index], np.ndarray)
                else row[index]
                for index in columns.keys()
            }
            for row in rows
        ]
        return inserted_records

    def preprocess_records_before_comparison(self, records: list[dict[str, t.Any]]) -> list[dict[str, t.Any]]:
        """Preprocess the records before comparison (if required).

        For Databricks we use a `databricks_ingested_timestamp` field to track when the records were ingested into the destination.
        For this timestamp, we use now64(), which is not suitable for comparison, so we exclude it.
        """
        return [{k: v for k, v in record.items() if k != "databricks_ingested_timestamp"} for record in records]

    async def assert_no_data_in_destination(self, team_id: int) -> None:
        """Assert that no data was written to Databricks."""
        try:
            records = await self.get_inserted_records(
                team_id=team_id,
                json_columns=[],
            )
            assert len(records) == 0
        except ServerOperationError as e:
            if "TABLE_OR_VIEW_NOT_FOUND" in str(e):
                return
            raise

    @contextlib.contextmanager
    def cursor(self, team_id: int):
        destination_config = self.get_destination_config(team_id)

        def _get_credential_provider():
            config = Config(
                host=f"https://{destination_config['server_hostname']}",
                client_id=destination_config["client_id"],
                client_secret=destination_config["client_secret"],
            )
            return oauth_service_principal(config)

        with sql.connect(
            server_hostname=destination_config["server_hostname"],
            http_path=destination_config["http_path"],
            credentials_provider=_get_credential_provider,
        ) as connection:
            with connection.cursor() as cursor:
                yield cursor


class TestDatabricksBatchExportWorkflow(CommonWorkflowTests):
    """Databricks batch export tests using the common test workflow framework.

    This class inherits all the common test patterns and runs them specifically
    for the Databricks destination by providing the DatabricksDestinationTest
    implementation.
    """

    @pytest.fixture(autouse=True)
    def reduce_poll_interval(self):
        """Reduce the poll interval for the Databricks client, in order to speed up the tests."""
        with unittest.mock.patch(
            "products.batch_exports.backend.temporal.destinations.databricks_batch_export.DatabricksClient.DEFAULT_POLL_INTERVAL",
            0.2,
        ):
            yield

    @pytest.fixture
    def destination_test(self, ateam: Team) -> Generator[DatabricksDestinationTest, t.Any, t.Any]:
        """Provide the Databricks-specific test implementation.

        This fixture also takes care of setting up the destination for the test.
        We create the catalog and schema for the test, dropping them on teardown.
        """
        destination_test = DatabricksDestinationTest()
        destination_config = destination_test.get_destination_config(ateam.pk)
        with destination_test.cursor(ateam.pk) as cursor:
            cursor.execute(f'USE CATALOG `{destination_config["catalog"]}`')
            cursor.execute(f'CREATE SCHEMA IF NOT EXISTS `{destination_config["schema"]}`')
            cursor.execute(f'USE SCHEMA `{destination_config["schema"]}`')

            yield destination_test

            cursor.execute(f'DROP SCHEMA IF EXISTS `{destination_config["schema"]}` CASCADE')

    @pytest.fixture
    def simulate_unexpected_error(self):
        with unittest.mock.patch(
            "products.batch_exports.backend.temporal.destinations.databricks_batch_export.Producer.start",
            side_effect=RetryableTestException("A useful error message"),
        ):
            yield

    # Additional tests specific to Databricks

    async def test_workflow_handles_merge_persons_data_in_follow_up_runs(
        self,
        destination_test: DatabricksDestinationTest,
        interval: str,
        generate_test_data,
        data_interval_start: dt.datetime,
        data_interval_end: dt.datetime,
        ateam,
        batch_export_for_destination,
        clickhouse_client,
    ):
        """Test that the Databricks batch export workflow handles merging new versions of person rows.

        This unit tests looks at the mutability handling capabilities of the aforementioned workflow.
        We will generate a new entry in the persons table for half of the persons exported in a first
        run of the workflow. We expect the new entries to have replaced the old ones in Databricks after
        the second run.
        """
        batch_export_model = BatchExportModel(name="persons", schema=None)

        inputs = destination_test.create_batch_export_inputs(
            team_id=ateam.pk,
            batch_export_id=str(batch_export_for_destination.id),
            data_interval_end=data_interval_end,
            interval=interval,
            batch_export_model=batch_export_model,
            batch_export_schema=None,
            **batch_export_for_destination.destination.config,
        )

        run = await destination_test.run_workflow(
            batch_export_id=batch_export_for_destination.id,
            inputs=inputs,
        )
        assert run.status == "Completed"
        _, persons_to_export_created = generate_test_data
        assert run.records_completed == len(persons_to_export_created)
        await assert_clickhouse_records_in_destination(
            destination_test=destination_test,
            team_id=ateam.pk,
            data_interval_start=data_interval_start,
            data_interval_end=data_interval_end,
            batch_export_model=batch_export_model,
            exclude_events=None,
            inputs=inputs,
        )

        # generate new versions of persons
        num_new_persons = len(persons_to_export_created) // 2
        for old_person in persons_to_export_created[:num_new_persons]:
            new_person_id = uuid.uuid4()
            new_person, _ = await generate_test_persons_in_clickhouse(
                client=clickhouse_client,
                team_id=ateam.pk,
                start_time=data_interval_start,
                end_time=data_interval_end,
                person_id=new_person_id,
                count=1,
                properties={"utm_medium": "referral", "$initial_os": "Linux", "new_property": "Something"},
            )

            await generate_test_person_distinct_id2_in_clickhouse(
                clickhouse_client,
                ateam.pk,
                person_id=uuid.UUID(new_person[0]["id"]),
                distinct_id=old_person["distinct_id"],
                version=old_person["version"] + 1,
                timestamp=old_person["_timestamp"],
            )

        # run the workflow again
        run = await destination_test.run_workflow(
            batch_export_id=batch_export_for_destination.id,
            inputs=inputs,
        )
        assert run.status == "Completed"
        assert run.records_completed == len(persons_to_export_created)
        await assert_clickhouse_records_in_destination(
            destination_test=destination_test,
            team_id=ateam.pk,
            data_interval_start=data_interval_start,
            data_interval_end=data_interval_end,
            batch_export_model=batch_export_model,
            exclude_events=None,
            inputs=inputs,
        )

    @pytest.mark.parametrize("use_automatic_schema_evolution", [True, False])
    async def test_workflow_handles_model_schema_changes(
        self,
        use_automatic_schema_evolution: bool,
        destination_test: DatabricksDestinationTest,
        interval: str,
        generate_test_data,
        data_interval_start: dt.datetime,
        data_interval_end: dt.datetime,
        ateam,
        batch_export_for_destination,
    ):
        """Test that the Databricks batch export workflow handles changes to the model schema.

        If we update the schema of the model we export, we should still be able to export the data without breaking
        existing exports.
        To replicate this situation we first export the data with the original schema, then delete a column in the
        destination and then rerun the export.

        Databricks supports automatic schema evolution, which means the target table will automatically be updated with
        the schema of the source table (no columns will ever be dropped from the target table however).

        If `use_automatic_schema_evolution` is True, we will use `WITH SCHEMA EVOLUTION` to enable automatic schema
        evolution. In this case, the target table will automatically be updated with the new column.

        If `use_automatic_schema_evolution` is False, we will not use `WITH SCHEMA EVOLUTION` and the target table will
        not be updated with the new column.

        """

        # create the table manually, specifically without the created_at column
        destination_config = batch_export_for_destination.destination.config
        catalog = destination_config["catalog"]
        schema = destination_config["schema"]
        table_name = destination_config["table_name"]
        query = f"""
        CREATE TABLE IF NOT EXISTS `{catalog}`.`{schema}`.`{table_name}` (
            `team_id` BIGINT,
            `distinct_id` STRING,
            `person_id` STRING,
            `properties` VARIANT,
            `person_distinct_id_version` BIGINT,
            `person_version` BIGINT,
            `is_deleted` BOOLEAN
        )
        USING DELTA
        COMMENT 'PostHog generated table'
        """
        with destination_test.cursor(ateam.pk) as cursor:
            cursor.execute(query)

        batch_export_model = BatchExportModel(name="persons", schema=None)

        inputs = destination_test.create_batch_export_inputs(
            team_id=ateam.pk,
            batch_export_id=str(batch_export_for_destination.id),
            data_interval_end=data_interval_end,
            interval=interval,
            batch_export_model=batch_export_model,
            batch_export_schema=None,
            **batch_export_for_destination.destination.config,
            use_automatic_schema_evolution=use_automatic_schema_evolution,
        )

        run = await destination_test.run_workflow(
            batch_export_id=batch_export_for_destination.id,
            inputs=inputs,
        )

        assert run.status == "Completed"
        _, persons_to_export_created = generate_test_data
        assert run.records_completed == len(persons_to_export_created)
        await assert_clickhouse_records_in_destination(
            destination_test=destination_test,
            team_id=ateam.pk,
            data_interval_start=data_interval_start,
            data_interval_end=data_interval_end,
            batch_export_model=batch_export_model,
            exclude_events=None,
            inputs=inputs,
            # if `use_automatic_schema_evolution` is False, we expect the created_at column to be dropped
            fields_to_exclude=["created_at"] if use_automatic_schema_evolution is False else [],
        )

        # check that the created_at column is present or not in the destination
        records_from_destination = await destination_test.get_inserted_records(
            team_id=ateam.pk,
            json_columns=destination_test.get_json_columns(inputs),
        )
        if use_automatic_schema_evolution is True:
            assert "created_at" in records_from_destination[0]
        else:
            assert "created_at" not in records_from_destination[0]
