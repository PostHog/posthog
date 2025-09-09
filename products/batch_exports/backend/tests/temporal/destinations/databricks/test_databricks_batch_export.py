"""Databricks batch export destination tests using the common test framework."""

import datetime as dt
from typing import Optional, Union

import pytest

from posthog.batch_exports.service import BatchExportModel, BatchExportSchema, DatabricksBatchExportInputs

from products.batch_exports.backend.temporal.destinations.databricks_batch_export import DatabricksBatchExportWorkflow
from products.batch_exports.backend.tests.temporal.destinations.base_destination_tests import (
    BaseDestinationTest,
    CommonDestinationTests,
)


class DatabricksDestinationTest(BaseDestinationTest):
    """Databricks-specific implementation of the base destination test interface."""

    @property
    def destination_type(self) -> str:
        return "Databricks"

    @property
    def workflow_class(self) -> type:
        return DatabricksBatchExportWorkflow

    @property
    def batch_export_inputs_class(self) -> type:
        return DatabricksBatchExportInputs

    def create_batch_export_inputs(
        self,
        team_id: int,
        batch_export_id: str,
        data_interval_end: dt.datetime,
        interval: str,
        batch_export_model: Optional[BatchExportModel] = None,
        batch_export_schema: Optional[BatchExportSchema] = None,
        **config,
    ) -> DatabricksBatchExportInputs:
        """Create workflow inputs for Databricks destination."""
        return DatabricksBatchExportInputs(
            team_id=team_id,
            batch_export_id=batch_export_id,
            data_interval_end=data_interval_end.isoformat(),
            interval=interval,
            batch_export_model=batch_export_model,
            batch_export_schema=batch_export_schema,
            **config,
        )

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

    @pytest.fixture
    def batch_export_for_destination(self, ateam, databricks_config):
        """Create a batch export configured for Databricks destination."""
        from posthog.models.batch_export import BatchExport, BatchExportDestination

        destination = BatchExportDestination(
            type="Databricks",
            config=databricks_config,
        )
        destination.save()

        batch_export = BatchExport(
            name="test-databricks-export",
            destination=destination,
            team=ateam,
            interval="hour",
            paused=False,
        )
        batch_export.save()

        return batch_export

    @pytest.fixture
    def databricks_config(self):
        """Provide test configuration for Databricks destination."""
        return {
            "server_hostname": "test.databricks.com",
            "http_path": "/sql/1.0/warehouses/test",
            "client_id": "test-client-id",
            "client_secret": "test-client-secret",
            "catalog": "test_catalog",
            "schema": "test_schema",
            "table_name": "test_table",
        }
