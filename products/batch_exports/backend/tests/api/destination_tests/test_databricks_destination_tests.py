import os

import pytest

from products.batch_exports.backend.api.destination_tests.base import Status
from products.batch_exports.backend.api.destination_tests.databricks import DatabricksEstablishConnectionTestStep

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
    }


@pytest.mark.parametrize(
    "step",
    [
        DatabricksEstablishConnectionTestStep(),
    ],
)
async def test_test_steps_fail_if_not_configured(step):
    result = await step.run()
    assert result.status == Status.FAILED
    assert result.message == "The test step cannot run as it's not configured."


class TestDatabricksEstablishConnectionTestStep:
    async def test_databricks_establish_connection_with_valid_connection_details(self, databricks_config):
        test_step = DatabricksEstablishConnectionTestStep(
            server_hostname=databricks_config["server_hostname"],
            http_path=databricks_config["http_path"],
            client_id=databricks_config["client_id"],
            client_secret=databricks_config["client_secret"],
        )
        result = await test_step.run()
        assert result.status == Status.PASSED

    async def test_databricks_establish_connection_with_wrong_server_hostname(self, databricks_config):
        test_step = DatabricksEstablishConnectionTestStep(
            server_hostname="garbage",
            http_path=databricks_config["http_path"],
            client_id=databricks_config["client_id"],
            client_secret=databricks_config["client_secret"],
        )
        result = await test_step.run()
        assert result.status == Status.FAILED
        assert result.message == "Failed to connect to Databricks. Please check that your connection details are valid."

    async def test_databricks_establish_connection_with_wrong_http_path(self, databricks_config):
        test_step = DatabricksEstablishConnectionTestStep(
            server_hostname=databricks_config["server_hostname"],
            http_path="garbage",
            client_id=databricks_config["client_id"],
            client_secret=databricks_config["client_secret"],
        )
        result = await test_step.run()
        assert result.status == Status.FAILED
        assert result.message == "Failed to connect to Databricks. Please check that your connection details are valid."

    async def test_databricks_establish_connection_with_invalid_credentials(self, databricks_config):
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
