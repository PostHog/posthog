import os
import datetime as dt

import pytest
from unittest.mock import patch

from databricks import sql
from databricks.sdk.core import Config, oauth_service_principal

from products.batch_exports.backend.api.destination_tests.base import Status
from products.batch_exports.backend.api.destination_tests.databricks import (
    DatabricksCatalogTestStep,
    DatabricksEstablishConnectionTestStep,
    DatabricksSchemaTestStep,
    DatabricksTableTestStep,
    DatabricksVolumeTestStep,
)
from products.batch_exports.backend.temporal.destinations.databricks_batch_export import (
    DatabricksInsufficientPermissionsError,
)

REQUIRED_ENV_VARS = (
    "DATABRICKS_BE_SERVER_HOSTNAME",
    "DATABRICKS_BE_HTTP_PATH",
    "DATABRICKS_BE_CLIENT_ID",
    "DATABRICKS_BE_CLIENT_SECRET",
)


pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(
        not all(env_var in os.environ for env_var in REQUIRED_ENV_VARS),
        reason=f"Databricks required env vars are not set: {', '.join(REQUIRED_ENV_VARS)}",
    ),
]


@pytest.fixture
def databricks_config():
    return {
        "server_hostname": os.getenv("DATABRICKS_BE_SERVER_HOSTNAME"),
        "http_path": os.getenv("DATABRICKS_BE_HTTP_PATH"),
        "client_id": os.getenv("DATABRICKS_BE_CLIENT_ID"),
        "client_secret": os.getenv("DATABRICKS_BE_CLIENT_SECRET"),
        "catalog": os.getenv("DATABRICKS_CATALOG", "batch_export_tests"),
    }


@pytest.fixture
def cursor(databricks_config):
    def _get_credential_provider():
        config = Config(
            host=f"https://{databricks_config['server_hostname']}",
            client_id=databricks_config["client_id"],
            client_secret=databricks_config["client_secret"],
        )
        return oauth_service_principal(config)

    with sql.connect(
        server_hostname=databricks_config["server_hostname"],
        http_path=databricks_config["http_path"],
        credentials_provider=_get_credential_provider,
    ) as connection:
        with connection.cursor() as cursor:
            yield cursor


@pytest.fixture
def schema(cursor, databricks_config):
    cursor.execute(f"USE CATALOG `{databricks_config['catalog']}`")
    schema = f"test_batch_exports_{dt.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"
    cursor.execute(f"CREATE SCHEMA IF NOT EXISTS `{schema}`")
    cursor.execute(f"USE SCHEMA `{schema}`")
    yield schema
    cursor.execute(f"DROP SCHEMA IF EXISTS `{schema}` CASCADE")


@pytest.fixture
def table(cursor, databricks_config, schema):
    table = "test_table"
    cursor.execute(f"CREATE TABLE IF NOT EXISTS `{table}` (id INT)")
    yield table
    cursor.execute(f"DROP TABLE IF EXISTS `{table}`")


@pytest.mark.parametrize(
    "step",
    [
        DatabricksEstablishConnectionTestStep(),
        DatabricksCatalogTestStep(),
        DatabricksSchemaTestStep(),
        DatabricksTableTestStep(),
        DatabricksVolumeTestStep(),
    ],
)
async def test_test_steps_fail_if_not_configured(step):
    result = await step.run()
    assert result.status == Status.FAILED
    assert result.message == "The test step cannot run as it's not configured."


class TestDatabricksEstablishConnectionTestStep:
    async def test_with_valid_connection_details(self, databricks_config):
        test_step = DatabricksEstablishConnectionTestStep(
            server_hostname=databricks_config["server_hostname"],
            http_path=databricks_config["http_path"],
            client_id=databricks_config["client_id"],
            client_secret=databricks_config["client_secret"],
        )
        result = await test_step.run()
        assert result.status == Status.PASSED

    async def test_with_wrong_server_hostname(self, databricks_config):
        test_step = DatabricksEstablishConnectionTestStep(
            server_hostname="garbage",
            http_path=databricks_config["http_path"],
            client_id=databricks_config["client_id"],
            client_secret=databricks_config["client_secret"],
        )
        result = await test_step.run()
        assert result.status == Status.FAILED
        assert result.message == "Failed to connect to Databricks. Please check that your connection details are valid."

    async def test_with_wrong_http_path(self, databricks_config):
        test_step = DatabricksEstablishConnectionTestStep(
            server_hostname=databricks_config["server_hostname"],
            http_path="garbage",
            client_id=databricks_config["client_id"],
            client_secret=databricks_config["client_secret"],
        )
        result = await test_step.run()
        assert result.status == Status.FAILED
        assert result.message == "Failed to connect to Databricks. Please check that your connection details are valid."

    async def test_with_invalid_credentials(self, databricks_config):
        test_step = DatabricksEstablishConnectionTestStep(
            server_hostname=databricks_config["server_hostname"],
            http_path=databricks_config["http_path"],
            client_id=databricks_config["client_id"],
            client_secret="garbage",
        )
        result = await test_step.run()
        assert result.status == Status.FAILED
        assert (
            result.message
            == "Failed to connect to Databricks: Error during request to server. invalid_client: Client authentication failed"
        )


class TestDatabricksCatalogTestStep:
    async def test_success(self, databricks_config):
        test_step = DatabricksCatalogTestStep(
            server_hostname=databricks_config["server_hostname"],
            http_path=databricks_config["http_path"],
            client_id=databricks_config["client_id"],
            client_secret=databricks_config["client_secret"],
            catalog=databricks_config["catalog"],
        )
        result = await test_step.run()
        assert result.status == Status.PASSED

    async def test_when_catalog_does_not_exist(self, databricks_config):
        test_step = DatabricksCatalogTestStep(
            server_hostname=databricks_config["server_hostname"],
            http_path=databricks_config["http_path"],
            client_id=databricks_config["client_id"],
            client_secret=databricks_config["client_secret"],
            catalog="are_you_there",
        )
        result = await test_step.run()
        assert result.status == Status.FAILED
        assert result.message == "Catalog 'are_you_there' not found"


class TestDatabricksSchemaTestStep:
    async def test_when_schema_does_not_exist(self, databricks_config):
        test_step = DatabricksSchemaTestStep(
            server_hostname=databricks_config["server_hostname"],
            http_path=databricks_config["http_path"],
            client_id=databricks_config["client_id"],
            client_secret=databricks_config["client_secret"],
            catalog=databricks_config["catalog"],
            schema="are_you_there",
        )
        result = await test_step.run()
        assert result.status == Status.FAILED
        assert result.message == "Schema 'are_you_there' not found"

    async def test_success(self, databricks_config, schema):
        test_step = DatabricksSchemaTestStep(
            server_hostname=databricks_config["server_hostname"],
            http_path=databricks_config["http_path"],
            client_id=databricks_config["client_id"],
            client_secret=databricks_config["client_secret"],
            catalog=databricks_config["catalog"],
            schema=schema,
        )
        result = await test_step.run()
        assert result.status == Status.PASSED


class TestDatabricksTableTestStep:
    async def test_success_when_table_exists(self, databricks_config, schema, table):
        test_step = DatabricksTableTestStep(
            server_hostname=databricks_config["server_hostname"],
            http_path=databricks_config["http_path"],
            client_id=databricks_config["client_id"],
            client_secret=databricks_config["client_secret"],
            catalog=databricks_config["catalog"],
            schema=schema,
            table_name=table,
        )
        result = await test_step.run()
        assert result.status == Status.PASSED

    async def test_success_when_table_does_not_exist(self, databricks_config, schema):
        test_step = DatabricksTableTestStep(
            server_hostname=databricks_config["server_hostname"],
            http_path=databricks_config["http_path"],
            client_id=databricks_config["client_id"],
            client_secret=databricks_config["client_secret"],
            catalog=databricks_config["catalog"],
            schema=schema,
            table_name="new_table",
        )
        result = await test_step.run()
        assert result.status == Status.PASSED


class TestDatabricksVolumeTestStep:
    async def test_success(self, databricks_config, schema):
        test_step = DatabricksVolumeTestStep(
            server_hostname=databricks_config["server_hostname"],
            http_path=databricks_config["http_path"],
            client_id=databricks_config["client_id"],
            client_secret=databricks_config["client_secret"],
            catalog=databricks_config["catalog"],
            schema=schema,
            table_name="test_volume",
        )
        result = await test_step.run()
        assert result.status == Status.PASSED

    async def test_failure_when_insufficient_permissions(self, databricks_config, schema):
        """Test that the test step fails when we don't have permissions to create a volume.

        We test this by mocking the DatabricksClient. We could avoid mocking the client but this would require more
        manual set up - as developers we would need to create one catalog where the service principal has permissions
        and one where it doesn't.
        """
        with patch(
            "products.batch_exports.backend.api.destination_tests.databricks.DatabricksClient.acreate_volume",
            side_effect=DatabricksInsufficientPermissionsError("Insufficient permissions"),
        ):
            test_step = DatabricksVolumeTestStep(
                server_hostname=databricks_config["server_hostname"],
                http_path=databricks_config["http_path"],
                client_id=databricks_config["client_id"],
                client_secret=databricks_config["client_secret"],
                catalog=databricks_config["catalog"],
                schema=schema,
                table_name="test_volume",
            )
            result = await test_step.run()
            assert result.status == Status.FAILED
            assert result.message == "A test volume could not be created: Insufficient permissions"
