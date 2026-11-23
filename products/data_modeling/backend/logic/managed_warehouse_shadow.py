"""
Whether a team's data modeling runs also build a managed-warehouse shadow.

Web code makes this decision when it starts a run, so the check lives outside the temporal
activities. Importing an activity module imports every activity and the warehouse sources.
"""

import os

from posthog.models import Team
from posthog.ph_client import feature_enabled_or_false

from products.managed_warehouse.backend.facade.api import (
    has_provisioned_warehouse,
    is_data_modeling_shadow_ready,
    is_dev_mode,
)
from products.managed_warehouse.backend.facade.feature_flags import DATA_MODELING_SHADOW_FLAG

FEATURE_FLAG = DATA_MODELING_SHADOW_FLAG


def _is_managed_warehouse_shadow_flag_enabled(team: Team) -> bool:
    if is_dev_mode():
        return os.environ.get("MANAGED_WAREHOUSE_SHADOW_ENABLED", "").lower() in ("1", "true")

    if not has_provisioned_warehouse(str(team.organization_id)):
        return False

    try:
        return feature_enabled_or_false(
            FEATURE_FLAG,
            str(team.pk),
            groups={
                "organization": str(team.organization_id),
                "project": str(team.id),
            },
            group_properties={
                "organization": {"id": str(team.organization_id)},
                "project": {"id": str(team.id)},
            },
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    except Exception:
        return False


def is_managed_warehouse_shadow_enabled(team: Team) -> bool:
    if not _is_managed_warehouse_shadow_flag_enabled(team):
        return False

    return is_data_modeling_shadow_ready(
        organization_id=team.organization_id,
        team_id=team.pk,
    )
