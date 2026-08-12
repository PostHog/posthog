from typing import TYPE_CHECKING

from django.conf import settings

from posthog.ph_client import feature_enabled_or_false

if TYPE_CHECKING:
    from posthog.models.team import Team

DATA_CATALOG_FEATURE_FLAG = "product-data-catalog"


def is_data_catalog_enabled(team: "Team") -> bool:
    """The `product-data-catalog` flag check, org-keyed. Canonical home for the check —
    gate any data-catalog surface (HogQL metrics table, MCP tools, prompts) through here."""
    if settings.DEBUG:
        return True
    return feature_enabled_or_false(
        DATA_CATALOG_FEATURE_FLAG,
        str(team.organization_id),
        groups={"organization": str(team.organization_id)},
        group_properties={"organization": {"id": str(team.organization_id)}},
        send_feature_flag_events=False,
    )
