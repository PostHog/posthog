"""Un-gated unit tests for the Snowflake insert activity's integration resolution.

These don't touch a real Snowflake instance, so (unlike test_activity_e2e.py) they run in CI.
"""

import pytest

from posthog.models.integration import Integration, SnowflakeIntegrationError

from products.batch_exports.backend.temporal.destinations.snowflake_batch_export import (
    SnowflakeIntegrationNotFoundError,
    _get_snowflake_integration,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]


async def test_get_snowflake_integration_raises_when_not_found(ateam):
    with pytest.raises(SnowflakeIntegrationNotFoundError):
        await _get_snowflake_integration(2147483647, ateam.pk)


async def test_get_snowflake_integration_rejects_wrong_kind(ateam):
    """An integration whose kind isn't snowflake can't be resolved as one.

    The serializer validates the kind on create/update, so this only happens if the integration's
    kind is changed out from under an existing export.
    """
    integration = await Integration.objects.acreate(
        team_id=ateam.pk,
        kind=Integration.IntegrationKind.SLACK,
        integration_id="not-snowflake",
        config={},
        sensitive_config={},
    )
    with pytest.raises(SnowflakeIntegrationError) as exc_info:
        await _get_snowflake_integration(integration.id, ateam.pk)
    assert "not a Snowflake integration" in str(exc_info.value)
    assert "kind='slack'" in str(exc_info.value)
