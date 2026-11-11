from posthog.constants import AvailableFeature
from posthog.models import Team, User

from products.access_control.backend.facade.contracts import PropertyAccessLevel
from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.event_definitions.backend.models.property_definition import PropertyDefinition


def hide_event_property(team: Team, user: User, name: str) -> None:
    organization = team.organization
    organization.available_product_features = [
        {"key": AvailableFeature.PROPERTY_ACCESS_CONTROL, "name": AvailableFeature.PROPERTY_ACCESS_CONTROL}
    ]
    organization.save()
    definition, _ = PropertyDefinition.objects.get_or_create(team=team, name=name, type=PropertyDefinition.Type.EVENT)
    PropertyAccessControl.objects.create(
        team=team,
        property_definition=definition,
        organization_member=user.organization_memberships.get(organization=organization),
        access_level=PropertyAccessLevel.NONE.value,
    )
