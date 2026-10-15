"""Un-gated unit tests for the Snowflake insert activity's integration resolution.

These don't touch a real Snowflake instance, so (unlike test_activity_e2e.py) they run in CI.
"""

import uuid

import pytest

from posthog.models.integration import Integration

from products.batch_exports.backend.temporal.destinations.snowflake_batch_export import (
    SnowflakeInsertInputs,
    SnowflakeIntegrationNotFoundError,
    SnowflakeIntegrationRequiredError,
    _get_snowflake_integration,
    insert_into_snowflake_activity_from_stage,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]


async def test_get_snowflake_integration_raises_when_not_found(ateam):
    with pytest.raises(SnowflakeIntegrationNotFoundError):
        await _get_snowflake_integration(2147483647, ateam.pk)


async def test_get_snowflake_integration_ignores_wrong_kind(ateam):
    """A non-snowflake integration doesn't match the kind-filtered lookup, so it reads as not found.

    Guards against the kind filter being dropped from the query, which would let an export resolve
    an unrelated integration.
    """
    integration = await Integration.objects.acreate(
        team_id=ateam.pk,
        kind=Integration.IntegrationKind.SLACK,
        integration_id="not-snowflake",
        config={},
        sensitive_config={},
    )
    with pytest.raises(SnowflakeIntegrationNotFoundError):
        await _get_snowflake_integration(integration.id, ateam.pk)


async def test_insert_activity_fails_when_export_has_no_integration(activity_environment, ateam):
    """An export with no linked integration cannot authenticate, so the run fails before connecting.

    The returned error also proves the failure is non-retryable: a retryable one re-raises instead,
    and retrying cannot supply credentials the export does not have.
    """
    inputs = SnowflakeInsertInputs(
        team_id=ateam.pk,
        batch_export_id=str(uuid.uuid4()),
        data_interval_start="2023-12-31T23:00:00+00:00",
        data_interval_end="2024-01-01T00:00:00+00:00",
        database="db",
        warehouse="wh",
        schema="public",
        table_name="events",
    )

    result = await activity_environment.run(insert_into_snowflake_activity_from_stage, inputs)

    assert result.error is not None
    assert result.error.type == SnowflakeIntegrationRequiredError.__name__
