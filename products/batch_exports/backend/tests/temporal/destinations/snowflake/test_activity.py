"""Un-gated unit tests for the Snowflake insert activity's integration resolution.

These don't touch a real Snowflake instance, so (unlike test_activity_e2e.py) they run in CI.
"""

import pytest

from posthog.models.integration import Integration

from products.batch_exports.backend.temporal.destinations.snowflake_batch_export import (
    SnowflakeIntegrationNotFoundError,
    _get_snowflake_integration,
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
