from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, PropertyDefinition

from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.access_control.backend.property_access_control import PropertyAccessLevel


class TestPropertyAccessControlViewSet(APIBaseTest):
    def setUp(self):
        super().setUp()
        # Write operations require project admin privileges
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        # Property access control management requires the PROPERTY_ACCESS_CONTROL entitlement.
        self.organization.available_product_features = [
            {"name": AvailableFeature.PROPERTY_ACCESS_CONTROL, "key": AvailableFeature.PROPERTY_ACCESS_CONTROL}
        ]
        self.organization.save()

        self.prop_def = PropertyDefinition.objects.create(
            team=self.team,
            name="secret_field",
            property_type="String",
            type=PropertyDefinition.Type.EVENT,
        )
        self.url = f"/api/environments/{self.team.pk}/property_access_controls/"
        self.list_url = f"{self.url}?property_definition_id={self.prop_def.id}"

    def _post(self, data: dict):
        payload = {"property_definition_id": str(self.prop_def.id), **data}
        return self.client.post(self.url, payload, format="json")

    def test_list_empty(self):
        response = self.client.get(self.list_url)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["access_controls"] == []
        assert data["default_access_level"] == PropertyAccessLevel.READ_WRITE.value
        assert set(data["available_access_levels"]) == {e.value for e in PropertyAccessLevel}

    def test_list_missing_property_definition_id_returns_400(self):
        response = self.client.get(self.url)
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_default_rule(self):
        response = self._post({"access_level": PropertyAccessLevel.NONE.value})
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["access_level"] == PropertyAccessLevel.NONE.value

        # verify it shows up in list
        list_response = self.client.get(self.list_url)
        assert list_response.json()["default_access_level"] == PropertyAccessLevel.NONE.value
        assert len(list_response.json()["access_controls"]) == 1

    def test_create_member_override(self):
        response = self._post(
            {
                "access_level": PropertyAccessLevel.READ_WRITE.value,
                "organization_member": str(self.organization_membership.id),
            }
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["access_level"] == PropertyAccessLevel.READ_WRITE.value
        # PrimaryKeyRelatedField serializes the FK as the PK value
        assert str(response.json()["organization_member"]) == str(self.organization_membership.id)

    def test_create_role_override(self):
        from ee.models.rbac.role import Role

        role = Role.objects.create(name="Analyst", organization=self.organization)
        response = self._post(
            {
                "access_level": PropertyAccessLevel.READ.value,
                "role": str(role.id),
            }
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["access_level"] == PropertyAccessLevel.READ.value
        assert str(response.json()["role"]) == str(role.id)

    def test_update_existing_rule(self):
        # create a rule
        self._post({"access_level": PropertyAccessLevel.NONE.value})
        # update it
        response = self._post({"access_level": PropertyAccessLevel.READ_WRITE.value})
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["access_level"] == PropertyAccessLevel.READ_WRITE.value

        # only one rule should exist
        assert PropertyAccessControl.objects.filter(property_definition=self.prop_def).count() == 1

    def test_update_preserves_original_created_by(self):
        from posthog.models import User

        # initial creator is self.user (logged in via APIBaseTest)
        self._post({"access_level": PropertyAccessLevel.NONE.value})
        rule = PropertyAccessControl.objects.get(property_definition=self.prop_def)
        original_creator_id = rule.created_by_id
        assert original_creator_id == self.user.id

        # log in as a different admin and update the rule
        other_user = User.objects.create_and_join(
            organization=self.organization,
            email="other-admin@posthog.com",
            password="password",
            level=OrganizationMembership.Level.ADMIN,
        )
        self.client.force_login(other_user)

        response = self._post({"access_level": PropertyAccessLevel.READ_WRITE.value})
        assert response.status_code == status.HTTP_200_OK

        rule.refresh_from_db()
        # created_by must remain the original creator, not the editor
        assert rule.created_by_id == original_creator_id

    def test_delete_default_rule(self):
        # create a rule first
        self._post({"access_level": PropertyAccessLevel.NONE.value})
        assert PropertyAccessControl.objects.filter(property_definition=self.prop_def).count() == 1

        # delete it via DELETE
        response = self.client.delete(f"{self.url}?property_definition_id={self.prop_def.id}")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert PropertyAccessControl.objects.filter(property_definition=self.prop_def).count() == 0

    def test_delete_member_override(self):
        self._post(
            {
                "access_level": PropertyAccessLevel.READ_WRITE.value,
                "organization_member": str(self.organization_membership.id),
            }
        )
        assert PropertyAccessControl.objects.filter(property_definition=self.prop_def).count() == 1

        response = self.client.delete(
            f"{self.url}?property_definition_id={self.prop_def.id}"
            f"&organization_member={self.organization_membership.id}"
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert PropertyAccessControl.objects.filter(property_definition=self.prop_def).count() == 0

    def test_delete_missing_rule_returns_404(self):
        response = self.client.delete(f"{self.url}?property_definition_id={self.prop_def.id}")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_delete_missing_property_definition_id_returns_400(self):
        response = self.client.delete(self.url)
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_with_null_access_level_returns_400(self):
        response = self._post({"access_level": None})
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_list_with_multiple_rules(self):
        from ee.models.rbac.role import Role

        role = Role.objects.create(name="Analyst", organization=self.organization)

        # default rule
        self._post({"access_level": PropertyAccessLevel.NONE.value})
        # member override
        self._post(
            {
                "access_level": PropertyAccessLevel.READ_WRITE.value,
                "organization_member": str(self.organization_membership.id),
            }
        )
        # role override
        self._post(
            {"access_level": PropertyAccessLevel.READ.value, "role": str(role.id)},
        )

        response = self.client.get(self.list_url)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["access_controls"]) == 3
        assert data["default_access_level"] == PropertyAccessLevel.NONE.value

    def test_cross_org_role_rejected(self):
        from posthog.models import Organization

        from ee.models.rbac.role import Role

        other_org = Organization.objects.create(name="Other org")
        other_role = Role.objects.create(name="Other org role", organization=other_org)

        response = self._post(
            {
                "access_level": PropertyAccessLevel.READ.value,
                "role": str(other_role.id),
            }
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert PropertyAccessControl.objects.filter(property_definition=self.prop_def).count() == 0

    def test_cross_org_organization_member_rejected(self):
        from posthog.models import Organization, OrganizationMembership, User

        other_org = Organization.objects.create(name="Other org")
        other_user = User.objects.create(email="other@posthog.com")
        other_membership = OrganizationMembership.objects.create(
            organization=other_org, user=other_user, level=OrganizationMembership.Level.MEMBER
        )

        response = self._post(
            {
                "access_level": PropertyAccessLevel.READ.value,
                "organization_member": str(other_membership.id),
            }
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert PropertyAccessControl.objects.filter(property_definition=self.prop_def).count() == 0

    def test_delete_cross_org_role_rejected(self):
        from posthog.models import Organization

        from ee.models.rbac.role import Role

        other_org = Organization.objects.create(name="Other org")
        other_role = Role.objects.create(name="Other org role", organization=other_org)

        response = self.client.delete(f"{self.url}?property_definition_id={self.prop_def.id}&role={other_role.id}")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_non_admin_can_read_but_not_write(self):
        # Downgrade to regular member
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        # GET should work (read access)
        response = self.client.get(self.list_url)
        assert response.status_code == status.HTTP_200_OK

        # POST should be forbidden (write access requires admin)
        response = self._post({"access_level": PropertyAccessLevel.NONE.value})
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_create_forbidden_without_property_access_control_feature(self):
        # Org lost (or never had) the PROPERTY_ACCESS_CONTROL entitlement — writes must be blocked
        # so rules cannot be added or modified. Existing rules continue to affect query behavior.
        self.organization.available_product_features = []
        self.organization.save()

        response = self._post({"access_level": PropertyAccessLevel.NONE.value})
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert PropertyAccessControl.objects.filter(property_definition=self.prop_def).count() == 0

    def test_delete_forbidden_without_property_access_control_feature(self):
        # Create a rule while the feature is available
        self._post({"access_level": PropertyAccessLevel.NONE.value})
        assert PropertyAccessControl.objects.filter(property_definition=self.prop_def).count() == 1

        # Remove the feature — the user should no longer be able to delete existing rules
        self.organization.available_product_features = []
        self.organization.save()

        response = self.client.delete(f"{self.url}?property_definition_id={self.prop_def.id}")
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert PropertyAccessControl.objects.filter(property_definition=self.prop_def).count() == 1

    def test_list_allowed_without_property_access_control_feature(self):
        # Create a rule while the feature is available
        self._post({"access_level": PropertyAccessLevel.NONE.value})

        # Remove the feature — reads must still work so users can inspect rules that are
        # still being enforced at query time.
        self.organization.available_product_features = []
        self.organization.save()

        response = self.client.get(self.list_url)
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["default_access_level"] == PropertyAccessLevel.NONE.value
        assert len(response.json()["access_controls"]) == 1
