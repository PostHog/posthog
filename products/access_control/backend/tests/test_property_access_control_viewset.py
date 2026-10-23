from urllib.parse import urlencode

from posthog.test.base import APIBaseTest

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, PropertyDefinition, Team, User

from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.access_control.backend.models.role import Role
from products.access_control.backend.presentation.serializers import PropertyAccessControlUpdateSerializer
from products.access_control.backend.property_access_control import PropertyAccessLevel, get_restricted_property_names


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
        self.url = f"/api/projects/{self.team.pk}/property_access_controls/"
        self.list_url = f"{self.url}?property_definition_id={self.prop_def.id}"

    def _post(self, data: dict, *, ai_property: bool = False):
        selector = {"ai_property": "$ai_input"} if ai_property else {"property_definition_id": str(self.prop_def.id)}
        payload = {**selector, **data}
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

    def test_list_with_property_name_instead_of_id_returns_404(self):
        response = self.client.get(f"{self.url}?property_definition_id={self.prop_def.name}")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_create_default_rule(self):
        response = self._post({"access_level": PropertyAccessLevel.NONE.value})
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["access_level"] == PropertyAccessLevel.NONE.value

        # verify it shows up in list
        list_response = self.client.get(self.list_url)
        assert list_response.json()["default_access_level"] == PropertyAccessLevel.NONE.value
        assert len(list_response.json()["access_controls"]) == 1

    @parameterized.expand([("$ai_input",), ("$ai_output",), ("$ai_output_choices",)])
    def test_create_ai_rule_before_ingestion(self, property_name: str) -> None:
        response = self.client.post(self.url, {"ai_property": property_name, "access_level": "none"}, format="json")
        assert response.status_code == status.HTTP_200_OK
        definition = PropertyDefinition.objects.get(team=self.team, name=property_name)
        assert definition.type == PropertyDefinition.Type.EVENT
        assert definition.project_id == self.team.project_id
        assert get_restricted_property_names(
            team_id=self.team.id, user=None, property_type=PropertyDefinition.Type.EVENT
        ) == {property_name}

        repeated = self.client.post(self.url, {"ai_property": property_name, "access_level": "read"}, format="json")
        assert repeated.status_code == status.HTTP_200_OK
        assert repeated.json()["id"] == response.json()["id"]
        assert (
            self.client.get(f"{self.url}?property_definition_id={definition.id}").json()["default_access_level"]
            == "read"
        )
        assert (
            self.client.delete(f"{self.url}?property_definition_id={definition.id}").status_code
            == status.HTTP_204_NO_CONTENT
        )

    @parameterized.expand([(False,), (True,)])
    def test_ai_rule_reuses_existing_definition_and_preserves_other_rules(self, legacy_definition: bool) -> None:
        definition = PropertyDefinition.objects.create(
            team=self.team,
            project_id=None if legacy_definition else self.team.project_id,
            name="$ai_input",
            type=PropertyDefinition.Type.EVENT,
            property_type="String",
        )
        member_rule = PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=definition,
            organization_member=self.organization_membership,
            access_level="read",
        )
        PropertyAccessControl.objects.create(team=self.team, property_definition=definition, access_level="read")
        response = self.client.post(self.url, {"ai_property": "$ai_input", "access_level": "none"}, format="json")
        assert response.status_code == status.HTTP_200_OK
        rule = PropertyAccessControl.objects.get(id=response.json()["id"])
        assert rule.property_definition_id == definition.id
        assert rule.team_id == self.team.id
        assert (
            self.client.get(f"{self.url}?property_definition_id={definition.id}").json()["default_access_level"]
            == "none"
        )
        assert get_restricted_property_names(
            team_id=self.team.id, user=None, property_type=PropertyDefinition.Type.EVENT
        ) == {"$ai_input"}

        updated = self.client.post(
            self.url, {"property_definition_id": str(definition.id), "access_level": "read"}, format="json"
        )
        assert updated.status_code == status.HTTP_200_OK
        assert updated.json()["id"] == response.json()["id"]
        assert (
            self.client.get(f"{self.url}?property_definition_id={definition.id}").json()["default_access_level"]
            == "read"
        )
        assert (
            self.client.delete(f"{self.url}?property_definition_id={definition.id}").status_code
            == status.HTTP_204_NO_CONTENT
        )
        assert not PropertyAccessControl.objects.filter(id=rule.id).exists()
        definition.refresh_from_db()
        member_rule.refresh_from_db()
        assert definition.property_type == "String"
        assert member_rule.access_level == "read"
        assert PropertyDefinition.objects.filter(team=self.team, name="$ai_input").count() == 1

    @parameterized.expand([(True,), (False,)])
    def test_property_rule_rejects_definition_from_another_project(self, legacy_definition: bool) -> None:
        other_team = Team.objects.create(organization=self.organization)
        definition = PropertyDefinition.objects.create(
            team=other_team,
            project_id=None if legacy_definition else other_team.project_id,
            name="$ai_input",
            type=PropertyDefinition.Type.EVENT,
        )
        rule = PropertyAccessControl.objects.create(
            team=other_team, property_definition=definition, access_level="none"
        )
        assert (
            self.client.get(f"{self.url}?property_definition_id={definition.id}").status_code
            == status.HTTP_404_NOT_FOUND
        )
        assert (
            self.client.post(
                self.url, {"property_definition_id": str(definition.id), "access_level": "read"}, format="json"
            ).status_code
            == status.HTTP_404_NOT_FOUND
        )
        assert (
            self.client.delete(f"{self.url}?property_definition_id={definition.id}").status_code
            == status.HTTP_404_NOT_FOUND
        )
        rule.refresh_from_db()
        assert rule.access_level == "none"
        assert not PropertyAccessControl.objects.filter(team=self.team, property_definition=definition).exists()

    def test_unknown_ai_property_does_not_create_definition(self) -> None:
        response = self.client.post(self.url, {"ai_property": "input", "access_level": "none"}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not PropertyDefinition.objects.filter(team=self.team, name="input").exists()

    @parameterized.expand([(False,), (True,)])
    def test_create_member_override(self, ai_property: bool) -> None:
        response = self._post(
            {
                "access_level": PropertyAccessLevel.READ_WRITE.value,
                "organization_member": str(self.organization_membership.id),
            },
            ai_property=ai_property,
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["access_level"] == PropertyAccessLevel.READ_WRITE.value
        # PrimaryKeyRelatedField serializes the FK as the PK value
        assert str(response.json()["organization_member"]) == str(self.organization_membership.id)

    def _grant_role_based_access(self) -> None:
        self.organization.available_product_features = [
            {"name": AvailableFeature.PROPERTY_ACCESS_CONTROL, "key": AvailableFeature.PROPERTY_ACCESS_CONTROL},
            {"name": AvailableFeature.ROLE_BASED_ACCESS, "key": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()

    @parameterized.expand([(False,), (True,)])
    def test_create_role_override(self, ai_property: bool) -> None:
        from products.access_control.backend.models.role import Role

        self._grant_role_based_access()
        role = Role.objects.create(name="Analyst", organization=self.organization)
        response = self._post(
            {
                "access_level": PropertyAccessLevel.READ.value,
                "role": str(role.id),
            },
            ai_property=ai_property,
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["access_level"] == PropertyAccessLevel.READ.value
        assert str(response.json()["role"]) == str(role.id)

    @parameterized.expand([("default",), ("member",), ("role",)])
    def test_ai_rule_remains_visible_in_settings(self, scope: str) -> None:
        definition = PropertyDefinition.objects.create(
            team=self.team,
            project_id=self.team.project_id,
            name="$ai_input",
            type=PropertyDefinition.Type.EVENT,
        )
        subject: dict[str, str] = {}
        query: dict[str, str] = {}
        if scope == "member":
            subject["organization_member"] = str(self.organization_membership.id)
            query["member_id"] = str(self.organization_membership.id)
        elif scope == "role":
            self._grant_role_based_access()
            role = Role.objects.create(name="Analyst", organization=self.organization)
            subject["role"] = str(role.id)
            query["role_id"] = str(role.id)

        response = self.client.post(
            self.url, {"ai_property": "$ai_input", "access_level": "none", **subject}, format="json"
        )
        assert response.status_code == status.HTTP_200_OK
        settings_url = f"/api/projects/{self.team.project_id}/access_control_{scope}_properties/"
        listed = self.client.get(settings_url, query)
        assert listed.status_code == status.HTTP_200_OK
        assert listed.json()["results"] == [
            {
                "property_definition_id": str(definition.id),
                "property": "$ai_input",
                "property_type": "event",
                "access_level": "none",
            }
        ]

        delete_query = urlencode({"property_definition_id": str(definition.id), **subject})
        deleted = self.client.delete(f"{self.url}?{delete_query}")
        assert deleted.status_code == status.HTTP_204_NO_CONTENT
        assert self.client.get(settings_url, query).json()["results"] == []

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
        from products.access_control.backend.models.role import Role

        self._grant_role_based_access()
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

    @parameterized.expand([(False,), (True,)])
    def test_cross_org_role_rejected(self, ai_property: bool) -> None:
        from posthog.models import Organization

        from products.access_control.backend.models.role import Role

        self._grant_role_based_access()
        other_org = Organization.objects.create(name="Other org")
        other_role = Role.objects.create(name="Other org role", organization=other_org)

        response = self._post(
            {
                "access_level": PropertyAccessLevel.READ.value,
                "role": str(other_role.id),
            },
            ai_property=ai_property,
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert PropertyAccessControl.objects.filter(property_definition=self.prop_def).count() == 0
        assert not PropertyDefinition.objects.filter(team=self.team, name="$ai_input").exists()

    @parameterized.expand([(False,), (True,)])
    def test_cross_org_organization_member_rejected(self, ai_property: bool) -> None:
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
            },
            ai_property=ai_property,
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert PropertyAccessControl.objects.filter(property_definition=self.prop_def).count() == 0
        assert not PropertyDefinition.objects.filter(team=self.team, name="$ai_input").exists()

    def test_delete_cross_org_role_rejected(self):
        from posthog.models import Organization

        from products.access_control.backend.models.role import Role

        self._grant_role_based_access()
        other_org = Organization.objects.create(name="Other org")
        other_role = Role.objects.create(name="Other org role", organization=other_org)

        response = self.client.delete(f"{self.url}?property_definition_id={self.prop_def.id}&role={other_role.id}")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @parameterized.expand([(False,), (True,)])
    def test_member_with_implicit_project_admin_can_read_but_not_write(self, ai_property: bool) -> None:
        self.organization.available_product_features = [
            {
                "name": AvailableFeature.PROPERTY_ACCESS_CONTROL,
                "key": AvailableFeature.PROPERTY_ACCESS_CONTROL,
            },
            {"name": AvailableFeature.ACCESS_CONTROL, "key": AvailableFeature.ACCESS_CONTROL},
        ]
        self.organization.save()
        member = User.objects.create_and_join(
            organization=self.organization,
            email="member@posthog.com",
            password="password",
            level=OrganizationMembership.Level.MEMBER,
        )
        member_membership = OrganizationMembership.objects.get(organization=self.organization, user=member)
        rule = PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.prop_def,
            access_level=PropertyAccessLevel.NONE.value,
            organization_member=member_membership,
            created_by=self.user,
        )
        self.client.force_login(member)

        response = self.client.get(self.list_url)
        assert response.status_code == status.HTTP_200_OK

        response = self._post({"access_level": PropertyAccessLevel.READ_WRITE.value}, ai_property=ai_property)
        assert response.status_code == status.HTTP_403_FORBIDDEN

        response = self.client.delete(
            f"{self.url}?property_definition_id={self.prop_def.id}&organization_member={member_membership.id}"
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert PropertyAccessControl.objects.filter(id=rule.id).exists()
        assert not PropertyDefinition.objects.filter(team=self.team, name="$ai_input").exists()

    @parameterized.expand([(False,), (True,)])
    def test_create_forbidden_without_property_access_control_feature(self, ai_property: bool) -> None:
        # Org lost (or never had) the PROPERTY_ACCESS_CONTROL entitlement — writes must be blocked
        # so rules cannot be added or modified. Existing rules continue to affect query behavior.
        self.organization.available_product_features = []
        self.organization.save()

        response = self._post({"access_level": PropertyAccessLevel.NONE.value}, ai_property=ai_property)
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert PropertyAccessControl.objects.filter(property_definition=self.prop_def).count() == 0
        # The gate runs before the body is validated, so an invalid body is still a 403 and not a 400
        assert self._post({}).status_code == status.HTTP_403_FORBIDDEN
        assert not PropertyDefinition.objects.filter(team=self.team, name="$ai_input").exists()

    @parameterized.expand([(False,), (True,)])
    def test_role_rule_forbidden_without_role_based_access_feature(self, ai_property: bool) -> None:
        from products.access_control.backend.models.role import Role

        role = Role.objects.create(name="Analyst", organization=self.organization)
        response = self._post(
            {"access_level": PropertyAccessLevel.READ.value, "role": str(role.id)}, ai_property=ai_property
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert PropertyAccessControl.objects.filter(property_definition=self.prop_def).count() == 0
        assert not PropertyDefinition.objects.filter(team=self.team, name="$ai_input").exists()

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


class TestPropertyAccessControlUpdateSerializer(SimpleTestCase):
    @parameterized.expand(
        [
            ({},),
            ({"property_definition_id": "existing", "ai_property": "$ai_input"},),
            ({"ai_property": "input"},),
            ({"ai_property": "$ai_unknown"},),
        ]
    )
    def test_invalid_property_selector(self, selector: dict[str, str]) -> None:
        serializer = PropertyAccessControlUpdateSerializer(data={**selector, "access_level": "none"})
        assert not serializer.is_valid()
