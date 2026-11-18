import dataclasses
from collections.abc import Collection, Mapping
from typing import Any, Optional

from django.db.models import Q

from posthog.models.activity_logging.activity_log import ActivityContextBase, ActivityLog

_CONTEXT_KEY = "property_value_visibility"

# Restricted group property names keyed by group type index. The None key applies to every group type.
GroupPropertyNamesByType = Mapping[Optional[int], frozenset[str]]


@dataclasses.dataclass(frozen=True)
class GroupActivityContext(ActivityContextBase):
    group_type_index: int


def group_type_index_of(detail: Mapping[str, Any]) -> Optional[int]:
    """The group type a Group entry was logged for, or None for entries logged before the type was recorded."""
    context = detail.get("context")
    if not isinstance(context, Mapping):
        return None
    group_type_index = context.get("group_type_index")
    if isinstance(group_type_index, bool) or not isinstance(group_type_index, int):
        return None
    return group_type_index


def group_property_names_for_type(
    names_by_type: GroupPropertyNamesByType, group_type_index: Optional[int]
) -> frozenset[str]:
    """Names restricted for one group type. Without a type, any group type's restriction applies."""
    if group_type_index is None:
        return frozenset().union(*names_by_type.values())
    return names_by_type.get(group_type_index, frozenset()) | names_by_type.get(None, frozenset())


def _name_overlaps_q(restricted_names: Collection[str]) -> Q:
    # Mirrors property_key_overlaps_restriction: the key equals a name or one of its dot-path parents,
    # or sits under a name.
    exact: set[str] = set()
    query = Q()
    for name in restricted_names:
        segments = name.split(".")
        exact.update(".".join(segments[:length]) for length in range(1, len(segments) + 1))
        query |= Q(detail__name__startswith=f"{name}.")
    return query | Q(detail__name__in=sorted(exact))


def hidden_group_values_q(names_by_type: GroupPropertyNamesByType) -> Optional[Q]:
    """Matches Group entries whose logged values are hidden for these restrictions, or None when none are."""
    if not any(names_by_type.values()):
        return None
    query = Q(detail__context__group_type_index__isnull=True) & _name_overlaps_q(
        group_property_names_for_type(names_by_type, None)
    )
    if names_by_type.get(None):
        query |= _name_overlaps_q(names_by_type[None])
    for group_type_index, names in names_by_type.items():
        if group_type_index is not None and names:
            query |= Q(detail__context__group_type_index=group_type_index) & _name_overlaps_q(names)
    return Q(scope="Group") & query


class PropertyValueVisibility:
    """Hides logged property values that property access control restricts for the requesting user.

    Group entries name the property in `detail.name` and record the group type in
    `detail.context.group_type_index`. Entries logged before the type was recorded match a name restricted
    for any group type.
    """

    def __init__(self, user: Any) -> None:
        self._user = user if getattr(user, "is_authenticated", False) else None
        self._restricted_group_properties: dict[int, GroupPropertyNamesByType] = {}
        self._admin_of_organization: dict[Any, bool] = {}

    @classmethod
    def from_serializer_context(cls, context: Mapping[str, Any]) -> Optional["PropertyValueVisibility"]:
        request = context.get("request")
        if request is None:
            return None
        visibility = context.get(_CONTEXT_KEY)
        if visibility is None:
            visibility = cls(getattr(request, "user", None))
            if isinstance(context, dict):
                context[_CONTEXT_KEY] = visibility
        return visibility

    def apply(self, entry: ActivityLog, detail: Any) -> Any:
        if entry.scope != "Group" or entry.team_id is None or not isinstance(detail, Mapping):
            return detail
        name = detail.get("name")
        changes = detail.get("changes")
        if not isinstance(name, str) or not isinstance(changes, list):
            return detail
        names_by_type = self.hidden_group_property_names_by_type(entry.team_id, entry.organization_id)
        if not names_by_type:
            return detail
        from products.access_control.backend.facade import api as access_control_api  # noqa: PLC0415

        # Serializers drop detail.context, so read the group type from the stored entry.
        stored = entry.detail if isinstance(entry.detail, Mapping) else {}
        group_type_index = group_type_index_of(stored)
        if group_type_index is None:
            group_type_index = group_type_index_of(detail)
        restricted = group_property_names_for_type(names_by_type, group_type_index)
        if not access_control_api.property_key_overlaps_restriction(name, restricted):
            return detail
        return {
            **detail,
            "changes": [
                {**change, "before": None, "after": None} if isinstance(change, Mapping) else change
                for change in changes
            ],
        }

    def add_to_serializer_context(self, context: dict[str, Any]) -> None:
        context[_CONTEXT_KEY] = self

    def hidden_group_property_names_by_type(self, team_id: int, organization_id: Any) -> GroupPropertyNamesByType:
        if self._is_organization_admin(organization_id):
            return {}
        return self._restricted_group_property_names_by_type(team_id)

    def hidden_group_values_filter(self, team_id: int, organization_id: Any) -> Optional[Q]:
        """Matches Group entries of this team whose values `apply` hides, or None when it hides none."""
        return hidden_group_values_q(self.hidden_group_property_names_by_type(team_id, organization_id))

    def _is_organization_admin(self, organization_id: Any) -> bool:
        # Org admins bypass property rules, so skip loading restrictions for them.
        if self._user is None or organization_id is None:
            return False
        if organization_id not in self._admin_of_organization:
            from posthog.models import OrganizationMembership  # noqa: PLC0415

            self._admin_of_organization[organization_id] = OrganizationMembership.objects.filter(
                user=self._user,
                organization_id=organization_id,
                level__gte=OrganizationMembership.Level.ADMIN,
            ).exists()
        return self._admin_of_organization[organization_id]

    def _restricted_group_property_names_by_type(self, team_id: int) -> GroupPropertyNamesByType:
        if team_id not in self._restricted_group_properties:
            from products.access_control.backend.facade import api as access_control_api  # noqa: PLC0415

            self._restricted_group_properties[team_id] = {
                group_type_index: names
                for group_type_index, names in access_control_api.get_restricted_group_property_names_by_type_index(
                    user=self._user, team_id=team_id
                ).items()
                if names
            }
        return self._restricted_group_properties[team_id]
