"""Access rules for referencing another project's insight from a cross-project dashboard."""

from typing import cast

from rest_framework import serializers

from posthog.models import Team, User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.product_analytics.backend.facade.models import Insight

NOT_AVAILABLE = "That insight is not available to you."


def assert_can_reference_insight(user: User, project_id: int, insight_id: int) -> None:
    """Allow a tile to reference an insight only when the user can already view it.

    This is a usability rule, not the security boundary. Every reader fetches each tile from
    that project's own insight endpoint, which enforces their own access independently.
    """
    team = Team.objects.filter(pk=project_id).first()
    if team is None:
        raise serializers.ValidationError({"project_id": NOT_AVAILABLE})

    user_access_control = UserAccessControl(user=cast(User, user), team=team)

    # Resource and object rules fall back to a permissive default, so on their own they grant
    # access in a project the user was explicitly denied. Project access is a separate check.
    if not user_access_control.has_project_access:
        raise serializers.ValidationError({"project_id": NOT_AVAILABLE})

    insight = Insight.objects.filter(pk=insight_id, team__project_id=team.project_id).first()
    if insight is None:
        raise serializers.ValidationError({"insight_id": NOT_AVAILABLE})

    if not user_access_control.check_access_level_for_object(insight, "viewer"):
        raise serializers.ValidationError({"insight_id": NOT_AVAILABLE})
