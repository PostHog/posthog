"""Tests for the Hubspot source.

NOTE: Some of these tests require access to the Hubspot API. These are marked with `SKIP_IF_MISSING_HUBSPOT_CREDENTIALS`.
To run these tests you'll need:
- A Hubspot account
- The HUBSPOT_APP_CLIENT_ID and HUBSPOT_APP_CLIENT_SECRET environment variables (these are required for OAuth2
    authentication)
- The HUBSPOT_SECRET_KEY and HUBSPOT_REFRESH_TOKEN environment variables.
    - You can obtain these by running the PostHog app locally, then linking a new Hubspot source using OAuth2 then
        grabbing these from the database (in external_data_source.job_inputs)

Then you can run the tests using:

```
OBJECT_STORAGE_ENDPOINT=http://localhost:19000 \
    HUBSPOT_SECRET_KEY="..." \
    HUBSPOT_REFRESH_TOKEN="..." \
    HUBSPOT_APP_CLIENT_SECRET="..." \
    HUBSPOT_APP_CLIENT_ID="..." \
pytest posthog/temporal/tests/data_imports/test_hubspot_source.py
```
"""

import os
import uuid
import urllib.parse

import pytest
from unittest.mock import patch

import structlog

from posthog.temporal.data_imports.sources.hubspot.hubspot import PROPERTY_LENGTH_LIMIT, _get_properties_str
from posthog.temporal.tests.data_imports.conftest import run_external_data_job_workflow

from products.data_warehouse.backend.models import ExternalDataSchema, ExternalDataSource

pytestmark = pytest.mark.usefixtures("minio_client")

REQUIRED_ENV_VARS = (
    "HUBSPOT_SECRET_KEY",
    "HUBSPOT_REFRESH_TOKEN",
    # These are needed for HubSpot OAuth app
    "HUBSPOT_APP_CLIENT_ID",
    "HUBSPOT_APP_CLIENT_SECRET",
)

logger = structlog.get_logger()


def hubspot_env_vars_are_set() -> bool:
    if not all(env_var in os.environ for env_var in REQUIRED_ENV_VARS):
        return False
    return True


SKIP_IF_MISSING_HUBSPOT_CREDENTIALS = pytest.mark.skipif(
    not hubspot_env_vars_are_set(),
    reason="Hubspot required env vars are not set",
)


@pytest.fixture
def external_data_source(team):
    source = ExternalDataSource.objects.create(
        source_id=str(uuid.uuid4()),
        connection_id=str(uuid.uuid4()),
        destination_id=str(uuid.uuid4()),
        team=team,
        status="running",
        source_type="Hubspot",
        job_inputs={
            "hubspot_secret_key": os.environ["HUBSPOT_SECRET_KEY"],
            "hubspot_refresh_token": os.environ["HUBSPOT_REFRESH_TOKEN"],
        },
    )
    return source


@pytest.fixture
def external_data_schema_full_refresh(external_data_source, team):
    schema = ExternalDataSchema.objects.create(
        name="contacts",
        team_id=team.pk,
        source_id=external_data_source.pk,
        sync_type="full_refresh",
        sync_type_config={},
    )
    return schema


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@SKIP_IF_MISSING_HUBSPOT_CREDENTIALS
async def test_hubspot_source_full_refresh(team, external_data_source, external_data_schema_full_refresh):
    """Test that a full refresh sync works as expected.

    Since this is using the Hubspot API, we don't know how many rows we'll get.
    """
    table_name = "hubspot.contacts"

    res = await run_external_data_job_workflow(
        team=team,
        external_data_source=external_data_source,
        external_data_schema=external_data_schema_full_refresh,
        table_name=table_name,
        expected_rows_synced=None,
        expected_total_rows=None,
    )
    # just assert some basic properties of the results
    assert res.results is not None
    assert len(res.results) > 0
    assert res.columns is not None
    assert len(res.columns) > 0
    assert "id" in res.columns


def test_hubspot_get_properties():
    with patch("posthog.temporal.data_imports.sources.hubspot.hubspot._get_property_names") as mock_get_property_names:
        mock_get_property_names.return_value = [
            "address",
            "email",
            "date_of_birth",
        ]
        props_str = _get_properties_str(
            props=["id", "name"],
            api_key="dummy_api_key",
            refresh_token="dummy_refresh_token",
            object_type="contact",
            logger=logger,
        )
    # default props should come first, followed by custom props
    assert props_str == "id,name,address,email,date_of_birth"


def test_hubspot_get_properties_without_custom_props():
    props_str = _get_properties_str(
        props=["id", "name"],
        api_key="dummy_api_key",
        refresh_token="dummy_refresh_token",
        object_type="contact",
        include_custom_props=False,
        logger=logger,
    )
    assert props_str == "id,name"


def test_hubspot_get_properties_when_no_custom_props_exist():
    with patch("posthog.temporal.data_imports.sources.hubspot.hubspot._get_property_names") as mock_get_property_names:
        mock_get_property_names.return_value = [
            "id",
            "name",
        ]
        props_str = _get_properties_str(
            props=["id", "name"],
            api_key="dummy_api_key",
            refresh_token="dummy_refresh_token",
            object_type="contact",
            logger=logger,
        )
    assert props_str == "id,name"


def test_hubspot_get_properties_when_no_default_props_exist():
    with patch("posthog.temporal.data_imports.sources.hubspot.hubspot._get_property_names") as mock_get_property_names:
        mock_get_property_names.return_value = [
            "id",
            "name",
        ]
        props_str = _get_properties_str(
            props=[],
            api_key="dummy_api_key",
            refresh_token="dummy_refresh_token",
            object_type="contact",
            logger=logger,
        )
    assert props_str == "id,name"


def test_hubspot_get_properties_url_length_limit():
    # Create a list of property names that will exceed the URL length limit
    long_props = [f"custom_property_{i}" for i in range(1000)]

    with patch("posthog.temporal.data_imports.sources.hubspot.hubspot._get_property_names") as mock_get_property_names:
        mock_get_property_names.return_value = long_props

        # Capture the warning log
        with patch.object(logger, "warning") as mock_warning:
            props_str = _get_properties_str(
                props=["id", "name"],
                api_key="dummy_api_key",
                refresh_token="dummy_refresh_token",
                object_type="contact",
                logger=logger,
            )
            # check that the default props are included
            assert props_str.split(",")[0] == "id"
            assert props_str.split(",")[1] == "name"

            # Verify the returned string is truncated
            assert len(props_str.split(",")) < len(long_props)
            assert len(urllib.parse.quote(props_str)) <= PROPERTY_LENGTH_LIMIT

            # check that the warning was logged
            mock_warning.assert_called_once()
            assert "Your request to Hubspot is too long to process" in mock_warning.call_args[0][0]
