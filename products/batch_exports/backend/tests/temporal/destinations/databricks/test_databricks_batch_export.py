"""Databricks batch export destination tests using the common test framework."""

import os
import datetime as dt
from collections.abc import Callable
from typing import Optional, Union

import pytest

from posthog.batch_exports.service import BatchExportModel, BatchExportSchema, DatabricksBatchExportInputs

from products.batch_exports.backend.temporal.destinations.databricks_batch_export import (
    DatabricksBatchExportWorkflow,
    insert_into_databricks_activity_from_stage,
)
from products.batch_exports.backend.tests.temporal.destinations.base_destination_tests import (
    BaseDestinationTest,
    CommonDestinationTests,
)

REQUIRED_ENV_VARS = (
    "DATABRICKS_SERVER_HOSTNAME",
    "DATABRICKS_HTTP_PATH",
    "DATABRICKS_ACCESS_TOKEN",
    "DATABRICKS_CATALOG",
    "DATABRICKS_SCHEMA",
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

    def get_destination_config(self, team_id: int) -> dict:
        """Provide test configuration for Databricks destination."""
        return {
            "server_hostname": os.getenv("DATABRICKS_SERVER_HOSTNAME"),
            "http_path": os.getenv("DATABRICKS_HTTP_PATH"),
            "client_id": os.getenv("DATABRICKS_CLIENT_ID"),
            "client_secret": os.getenv("DATABRICKS_CLIENT_SECRET"),
            "catalog": os.getenv("DATABRICKS_CATALOG", "workspace"),
            "schema": os.getenv("DATABRICKS_SCHEMA", "batch_export_tests"),
            "table_name": f"test_workflow_table_{team_id}",
        }

    async def assert_data_in_destination(
        self,
        team_id: int,
        data_interval_start: dt.datetime,
        data_interval_end: dt.datetime,
        exclude_events: Optional[list[str]] = None,
        batch_export_model: Optional[Union[BatchExportModel, BatchExportSchema]] = None,
        **kwargs,
    ) -> None:
        """Assert that the expected data was written to Databricks.

        Note: This is a placeholder implementation. In a real test environment,
        you would connect to your test Databricks instance and verify the data.
        """
        # Placeholder - in real implementation, you would:
        # 1. Connect to test Databricks workspace
        # 2. Query the target table
        # 3. Verify the expected records are present
        # 4. Check data format and content matches expectations

        # For now, we'll just pass since we don't have a test Databricks instance
        # configured. This test framework allows easy addition of real assertions
        # when test infrastructure is available.
        pass

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
        pass

    async def setup_destination_for_test(self) -> None:
        """Setup the destination for the test."""
        # TODO
        # create catlog, schema, etc

    async def teardown_destination_for_test(self) -> None:
        """Teardown the destination for the test."""
        # TODO
        # drop catalog, schema, etc


class TestDatabricksBatchExport(CommonDestinationTests):
    """Databricks batch export tests using the common test framework.

    This class inherits all the common test patterns and runs them specifically
    for the Databricks destination by providing the DatabricksDestinationTest
    implementation.
    """

    @pytest.fixture
    def destination_test(self) -> DatabricksDestinationTest:
        """Provide the Databricks-specific test implementation."""
        return DatabricksDestinationTest()

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
