from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, Team

from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.access_control.backend.models.role import Role, RoleMembership
from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.cdp.backend.models.plugin import Plugin, PluginConfig
from products.event_definitions.backend.models import PropertyDefinition


class TestCDPPropertyAccess(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": feature, "name": feature}
            for feature in [
                AvailableFeature.PROPERTY_ACCESS_CONTROL,
                AvailableFeature.ROLE_BASED_ACCESS,
                AvailableFeature.DATA_PIPELINES,
            ]
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.property = PropertyDefinition.objects.create(
            team=self.team, name="private_note", type=PropertyDefinition.Type.EVENT
        )
        self.rule = PropertyAccessControl.objects.create(
            team=self.team, property_definition=self.property, access_level="none"
        )
        reload_workers = patch("products.cdp.backend.models.hog_functions.hog_function.reload_hog_functions_on_workers")
        reload_workers.start()
        self.addCleanup(reload_workers.stop)
        self.url = f"/api/projects/{self.team.pk}/hog_functions/"

    @parameterized.expand(
        [
            ("destination", PropertyDefinition.Type.EVENT),
            ("destination", PropertyDefinition.Type.PERSON),
            ("transformation", PropertyDefinition.Type.EVENT),
        ]
    )
    def test_restricted_member_cannot_create_function(self, function_type: str, property_type: int) -> None:
        self.property.type = property_type
        self.property.save()

        response = self.client.post(
            self.url,
            {"name": "Test pipeline", "type": function_type, "hog": "print(event.properties.private_note);"},
        )

        assert response.status_code == 403, response.json()
        assert "property access" in response.json()["detail"].lower()
        assert not HogFunction.objects.filter(team=self.team).exists()

    @parameterized.expand(
        [
            ("patch", ""),
            ("post", "/invocations"),
            ("post", "/rerun"),
            ("post", "/publish"),
            ("post", "/discard_draft"),
            ("post", "/revisions/1/restore"),
            ("get", "/logs"),
        ]
    )
    def test_restricted_member_cannot_execute_or_change_existing_function(self, method: str, suffix: str) -> None:
        function = HogFunction.objects.create(team=self.team, name="Existing pipeline", hog="return null")

        response = getattr(self.client, method)(f"{self.url}{function.pk}{suffix}/", {"name": "Changed pipeline"})

        assert response.status_code == 403, response.json()
        assert "property access" in response.json()["detail"].lower()
        function.refresh_from_db()
        assert function.name == "Existing pipeline"

    def test_restricted_member_cannot_reorder_transformations(self) -> None:
        response = self.client.patch(f"{self.url}rearrange/", {"order": []})

        assert response.status_code == 403, response.json()
        assert "property access" in response.json()["detail"].lower()

    @parameterized.expand([("default",), ("member",), ("role",)])
    def test_effective_property_permissions_are_used(self, rule_scope: str) -> None:
        if rule_scope == "member":
            self.rule.organization_member = self.organization_membership
        elif rule_scope == "role":
            role = Role.objects.create(organization=self.organization, name="Restricted member")
            RoleMembership.objects.create(role=role, user=self.user, organization_member=self.organization_membership)
            self.rule.role = role
        self.rule.save()

        denied = self.client.post(self.url, {"name": "Test pipeline", "hog": "return null"})
        assert denied.status_code == 403, denied.json()

        self.rule.access_level = "read"
        self.rule.save()
        allowed = self.client.post(self.url, {"name": "Test pipeline", "hog": "return null"})
        assert allowed.status_code == 201, allowed.json()

    def test_member_read_override_allows_configuration(self) -> None:
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.property,
            organization_member=self.organization_membership,
            access_level="read",
        )

        response = self.client.post(self.url, {"name": "Test pipeline", "hog": "return null"})

        assert response.status_code == 201, response.json()

    def test_admin_can_configure_functions(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        response = self.client.post(self.url, {"name": "Test pipeline", "hog": "return null"})

        assert response.status_code == 201, response.json()

    def test_api_key_cannot_bypass_property_permissions(self) -> None:
        key = self.create_personal_api_key_with_scopes(["hog_function:write"])
        self.client.logout()

        response = self.client.post(
            self.url,
            {"name": "Test pipeline", "hog": "return null"},
            HTTP_AUTHORIZATION=f"Bearer {key}",
        )

        assert response.status_code == 403, response.json()
        assert "property access" in response.json()["detail"].lower()

    def test_restrictions_in_another_project_do_not_block_configuration(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other project")

        response = self.client.post(
            f"/api/projects/{other_team.pk}/hog_functions/", {"name": "Test pipeline", "hog": "return null"}
        )

        assert response.status_code == 201, response.json()

    def test_rules_are_inactive_without_property_access_control(self) -> None:
        self.organization.available_product_features = []
        self.organization.save()

        response = self.client.post(self.url, {"name": "Test pipeline", "hog": "return null"})

        assert response.status_code == 201, response.json()

    def test_restricted_member_can_read_configuration(self) -> None:
        function = HogFunction.objects.create(team=self.team, name="Existing pipeline", hog="return null")

        assert self.client.get(self.url).status_code == 200
        response = self.client.get(f"{self.url}{function.pk}/")
        assert response.status_code == 200, response.json()
        assert response.json()["name"] == "Existing pipeline"

    def test_restricted_member_cannot_create_zapier_hook(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.pk}/hooks/",
            {"event": "action_performed", "target": "https://hooks.zapier.com/hooks/standard/123/example"},
        )

        assert response.status_code == 403, response.json()
        assert "property access" in response.json()["detail"].lower()

    @parameterized.expand(
        [("plugin_configs",), ("pipeline_destination_configs",), ("pipeline_transformation_configs",)]
    )
    def test_restricted_member_cannot_edit_legacy_configuration(self, route: str) -> None:
        plugin = Plugin.objects.create(organization=self.organization, name="Test plugin", config_schema=[])
        config = PluginConfig.objects.create(team=self.team, plugin=plugin, config={}, enabled=False, order=0)

        response = self.client.patch(f"/api/projects/{self.team.pk}/{route}/{config.pk}/", {"enabled": True})

        assert response.status_code == 403, response.json()
        assert "property access" in response.json()["detail"].lower()
        config.refresh_from_db()
        assert not config.enabled

    def test_restricted_member_cannot_read_legacy_plugin_logs(self) -> None:
        plugin = Plugin.objects.create(organization=self.organization, name="Test plugin", config_schema=[])
        config = PluginConfig.objects.create(team=self.team, plugin=plugin, config={}, enabled=False, order=0)

        response = self.client.get(f"/api/projects/{self.team.pk}/plugin_configs/{config.pk}/logs/")

        assert response.status_code == 403, response.json()
        assert "property access" in response.json()["detail"].lower()
