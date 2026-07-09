"""
Emit PostHog analytics events for account changes.

These events power workflow triggers (e.g. "when the 'churn risk' tag is added
to an account, notify its CSM"). Events are sent to the customer's PostHog
project via their team's API token.
"""

from typing import Any

from posthog.api.capture import capture_batch_internal
from posthog.models.group_type_mapping import get_group_types_for_project
from posthog.models.tag import Tag
from posthog.models.user import User

from products.customer_analytics.backend.models import Account

EVENT_SOURCE = "customer_analytics_events"


def _account_groups(account: Account) -> dict[str, str] | None:
    """Map the team's account group type to this account's external_id.

    The ``$groups`` entry lets downstream account workflow actions prefill
    ``external_id`` via ``{groups.<type>.id}`` with zero manual input.
    """
    if not account.external_id:
        return None
    group_type_index = account.team.customer_analytics_config.account_group_type_index
    if group_type_index is None:
        return None
    group_types = get_group_types_for_project(account.team.project_id, caller_tag="customer_analytics/events")
    for mapping in group_types:
        if mapping["group_type_index"] == group_type_index:
            return {mapping["group_type"]: account.external_id}
    return None


def emit_account_tags_added(
    account: Account, tags: list[Tag], actor: User | None, workflow_id: str | None = None
) -> None:
    if not tags:
        return

    properties: dict[str, Any] = {
        "account_id": str(account.id),
        "account_external_id": account.external_id,
        "account_name": account.name,
        "actor_type": "user" if actor else ("workflow" if workflow_id else "system"),
        "actor_id": actor.id if actor else None,
        "actor_email": actor.email if actor else None,
        "workflow_id": workflow_id,
    }
    groups = _account_groups(account)
    if groups:
        properties["$groups"] = groups

    distinct_id = actor.distinct_id if actor and actor.distinct_id else f"account:{account.id}"
    capture_batch_internal(
        events=[
            {
                "event": "$account_tag_added",
                "distinct_id": distinct_id,
                "properties": {**properties, "tag": tag.name, "tag_id": str(tag.id)},
            }
            for tag in tags
        ],
        token=account.team.api_token,
        event_source=EVENT_SOURCE,
    ).raise_for_status()
