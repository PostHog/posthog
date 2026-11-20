from typing import TYPE_CHECKING

from django.db.models import QuerySet

from products.data_modeling.backend.facade.enums import NodeType
from products.data_modeling.backend.logic.flags import is_managed_viewset_enabled

if TYPE_CHECKING:
    from posthog.models.team import Team

    from products.access_control.backend.facade.user_access_control import UserAccessControl


def metric_nodes_hidden(user_access_control: "UserAccessControl") -> bool:
    return not user_access_control.check_access_level_for_resource("data_catalog", required_level="viewer")


def managed_views_hidden(team: "Team") -> bool:
    return not is_managed_viewset_enabled(team)


def exclude_hidden_nodes(queryset: QuerySet, team: "Team", user_access_control: "UserAccessControl") -> QuerySet:
    queryset = queryset.exclude(saved_query__deleted=True)
    if managed_views_hidden(team):
        queryset = queryset.exclude(saved_query__managed_viewset__isnull=False)
    if metric_nodes_hidden(user_access_control):
        return queryset.exclude(type=NodeType.METRIC)
    return queryset
