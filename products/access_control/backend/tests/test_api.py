from posthog.test.base import BaseTest

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, PropertyDefinition

from products.access_control.backend.facade.api import get_restricted_property_names
from products.access_control.backend.facade.contracts import PropertyAccessLevel
from products.access_control.backend.models.property_access_control import PropertyAccessControl


class TestGetRestrictedPropertyNames(BaseTest):
    def test_returns_immutable_names_for_requested_property_type(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.organization.available_product_features = [
            {
                "name": AvailableFeature.PROPERTY_ACCESS_CONTROL,
                "key": AvailableFeature.PROPERTY_ACCESS_CONTROL,
            }
        ]
        self.organization.save()
        event_property = PropertyDefinition.objects.create(
            team=self.team,
            name="restricted_event_property",
            property_type="String",
            type=PropertyDefinition.Type.EVENT,
        )
        person_property = PropertyDefinition.objects.create(
            team=self.team,
            name="restricted_person_property",
            property_type="String",
            type=PropertyDefinition.Type.PERSON,
        )
        PropertyAccessControl.objects.bulk_create(
            [
                PropertyAccessControl(
                    team=self.team,
                    property_definition=event_property,
                    organization_member=self.organization_membership,
                    access_level=PropertyAccessLevel.NONE.value,
                ),
                PropertyAccessControl(
                    team=self.team,
                    property_definition=person_property,
                    access_level=PropertyAccessLevel.NONE.value,
                ),
            ]
        )

        restricted_names = get_restricted_property_names(
            team_id=self.team.pk,
            user_id=self.user.pk,
            property_type=PropertyDefinition.Type.EVENT,
        )

        assert restricted_names == frozenset({"restricted_event_property"})
        assert isinstance(restricted_names, frozenset)
