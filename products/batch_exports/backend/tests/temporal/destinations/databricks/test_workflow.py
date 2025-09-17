"""Databricks batch export destination tests using the common test framework."""

import os
import json
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

from posthog.batch_exports.service import BatchExportField, DatabricksBatchExportInputs
from posthog.models.team import Team

from products.batch_exports.backend.temporal.destinations.databricks_batch_export import (
    DatabricksBatchExportWorkflow,
    databricks_default_fields,
    insert_into_databricks_activity_from_stage,
)
from products.batch_exports.backend.tests.temporal.destinations.base_destination_tests import (
    BaseDestinationTest,
    CommonWorkflowTests,
    RetryableTestException,
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
    def workflow_class(self) -> type:
        return DatabricksBatchExportWorkflow

    @property
    def main_activity(self) -> Callable:
        return insert_into_databricks_activity_from_stage

    @property
    def batch_export_inputs_class(self) -> type:
        return DatabricksBatchExportInputs

    @property
    def destination_default_fields(self) -> list[BatchExportField]:
        return databricks_default_fields()

    def get_json_columns(self, inputs: DatabricksBatchExportInputs) -> list[str]:
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
                "http_path": "invalid",
                "client_id": "invalid",
                "client_secret": "invalid",
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
        """Get the inserted records from Databricks.

        Note: This is a placeholder implementation. In a real test environment,
        you would connect to your test Databricks instance and verify the data.
        """
        config = self.get_destination_config(team_id)

        with self.cursor(team_id) as cursor:
            cursor.execute(f'USE CATALOG `{config["catalog"]}`')
            cursor.execute(f'USE SCHEMA `{config["schema"]}`')
            cursor.execute(f'SELECT * FROM `{config["table_name"]}`')
            rows = cursor.fetchall()
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
    """Databricks batch export tests using the common test framework.

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
