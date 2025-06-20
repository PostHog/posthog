from typing import Union
from uuid import UUID

from posthog.redis import get_client


ENV_ROLLBACK_REDIS_KEY = "@posthog/environments-rollback/triggered-org-ids"


def add_organization_to_rollback_list(organization_id: Union[str, UUID]) -> None:
    """Add an organization ID to the Redis set of orgs with triggered rollback."""
    redis_client = get_client()
    organization_id_str = str(organization_id)
    redis_client.sadd(ENV_ROLLBACK_REDIS_KEY, organization_id_str)


def is_organization_rollback_triggered(organization_id: Union[str, UUID]) -> bool:
    """Check if an organization has triggered environment rollback."""
    redis_client = get_client()
    organization_id_str = str(organization_id)
    return bool(redis_client.sismember(ENV_ROLLBACK_REDIS_KEY, organization_id_str))
