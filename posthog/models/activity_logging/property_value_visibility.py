from collections.abc import Mapping
from typing import Any, Optional

from posthog.models.activity_logging.activity_log import ActivityLog

_CONTEXT_KEY = "property_value_visibility"


class PropertyValueVisibility:
    """Hides logged property values that property access control restricts for the requesting user.

    Group entries name the property in `detail.name` but do not record the group type, so a name
    restricted for any group type hides the values.
    """

    def __init__(self, user: Any) -> None:
        self._user = user if getattr(user, "is_authenticated", False) else None
        self._restricted_group_properties: dict[int, frozenset[str]] = {}
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
        if name not in self.hidden_group_property_names(entry.team_id, entry.organization_id):
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

    def hidden_group_property_names(self, team_id: int, organization_id: Any) -> frozenset[str]:
        if self._is_organization_admin(organization_id):
            return frozenset()
        return self._restricted_group_property_names(team_id)

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

    def _restricted_group_property_names(self, team_id: int) -> frozenset[str]:
        if team_id not in self._restricted_group_properties:
            from products.access_control.backend.facade import api as access_control_api  # noqa: PLC0415
            from products.event_definitions.backend.models import PropertyDefinition  # noqa: PLC0415

            restrictions = access_control_api.get_restricted_properties_with_group_type_index_for_team(
                user=self._user, team_id=team_id
            )
            self._restricted_group_properties[team_id] = frozenset(
                restriction.name
                for restriction in restrictions
                if restriction.property_type == PropertyDefinition.Type.GROUP
            )
        return self._restricted_group_properties[team_id]
