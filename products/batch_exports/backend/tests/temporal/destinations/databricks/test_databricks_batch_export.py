"""Databricks batch export destination tests using the common test framework."""

import os
import json
import typing as t
import contextlib
from collections.abc import Callable

import pytest

from databricks import sql
from databricks.sdk.core import Config, oauth_service_principal

from posthog.batch_exports.service import BatchExportField, DatabricksBatchExportInputs
from posthog.models.team import Team

from products.batch_exports.backend.temporal.destinations.databricks_batch_export import (
    DatabricksBatchExportWorkflow,
    databricks_default_fields,
    insert_into_databricks_activity_from_stage,
)
from products.batch_exports.backend.tests.temporal.destinations.base_destination_tests import (
    BaseDestinationTest,
    CommonDestinationTests,
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
            "schema": os.getenv("DATABRICKS_SCHEMA", f"test_workflow_schema_{team_id}"),
            "table_name": f"test_workflow_table_{team_id}",
        }

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
                else row[index]
                for index in columns.keys()
            }
            for row in rows
        ]
        return inserted_records

    async def assert_no_data_in_destination(self, **kwargs) -> None:
        """Assert that no data was written to Databricks.

        Note: This is a placeholder implementation. In a real test environment,
        you would connect to your test Databricks instance and verify no data exists.
        """
        # Placeholder - in real implementation, you would:
        # 1. Connect to test Databricks workspace
        # 2. Query the target table
        # 3. Verify no records exist or table doesn't exist

        # For now, we'll just pass since we don't have a test Databricks instance
        assert False, "Not implemented"

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


class TestDatabricksBatchExport(CommonDestinationTests):
    """Databricks batch export tests using the common test framework.

    This class inherits all the common test patterns and runs them specifically
    for the Databricks destination by providing the DatabricksDestinationTest
    implementation.
    """

    @pytest.fixture
    def destination_test(self, ateam: Team) -> DatabricksDestinationTest:
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

    # @pytest.fixture
    # def batch_export_for_destination(self, ateam, databricks_config):
    #     """Create a batch export configured for Databricks destination."""

    #     destination = BatchExportDestination(
    #         type="Databricks",
    #         config=databricks_config,
    #     )
    #     destination.save()

    #     batch_export = BatchExport(
    #         name="test-databricks-export",
    #         destination=destination,
    #         team=ateam,
    #         interval="hour",
    #         paused=False,
    #     )
    #     batch_export.save()

    #     return batch_export

    # @pytest.fixture
    # def databricks_config(self):
    #     """Provide test configuration for Databricks destination."""
    #     return {
    #         "server_hostname": os.getenv("DATABRICKS_SERVER_HOSTNAME"),
    #         "http_path": os.getenv("DATABRICKS_HTTP_PATH"),
    #         "client_id": os.getenv("DATABRICKS_CLIENT_ID"),
    #         "client_secret": os.getenv("DATABRICKS_CLIENT_SECRET"),
    #         "catalog": os.getenv("DATABRICKS_CATALOG", "workspace"),
    #         "schema": os.getenv("DATABRICKS_SCHEMA", "batch_export_tests"),
    #         "table_name": os.getenv("DATABRICKS_TABLE_NAME"),
    #     }
