from datetime import timedelta
from uuid import uuid4

from posthog.test.base import APIBaseTest

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.organization import OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team import Team
from posthog.models.user import User
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.access_control.backend.models.access_control import AccessControl
from products.customer_analytics.backend.models import (
    AccountRelationshipDefinition,
    CustomPropertyDefinition,
    TargetType,
    UserCustomerAnalyticsConfig,
)


class TestUserCustomerAnalyticsConfigAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.endpoint = f"/api/projects/{self.team.id}/user_customer_analytics_config/@me/"

    def _custom_property(
        self, *, team: Team | None = None, target_type: TargetType = TargetType.ACCOUNT
    ) -> CustomPropertyDefinition:
        owning_team = team or self.team
        return CustomPropertyDefinition.objects.for_team(owning_team.id).create(
            team_id=owning_team.id,
            name=f"Property {uuid4()}",
            target_type=target_type.value,
        )

    def _relationship(self, *, team: Team | None = None) -> AccountRelationshipDefinition:
        owning_team = team or self.team
        return AccountRelationshipDefinition.objects.for_team(owning_team.id).create(
            team_id=owning_team.id,
            name=f"Relationship {uuid4()}",
        )

    def test_get_creates_empty_config_without_rewriting_an_explicit_empty_list(self) -> None:
        response = self.client.get(self.endpoint)

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        self.assertEqual(response.json(), {"pinned_properties": []})
        config = UserCustomerAnalyticsConfig.objects.for_team(self.team.id).get(user_id=self.user.id)
        self.assertEqual(config.properties, {"pinned_properties": []})

        legacy_definition = self._custom_property()
        config.properties = {"pinned_properties": [], "future_setting": "kept"}
        config.pinned_custom_property_definition_ids = [legacy_definition.id]
        config.save(update_fields=["properties", "pinned_custom_property_definition_ids"])
        updated_at = config.updated_at

        repeated = self.client.get(self.endpoint)

        self.assertEqual(repeated.status_code, status.HTTP_200_OK, repeated.json())
        self.assertEqual(repeated.json(), {"pinned_properties": []})
        config.refresh_from_db()
        self.assertEqual(config.properties, {"pinned_properties": [], "future_setting": "kept"})
        self.assertEqual(config.updated_at, updated_at)

    def test_get_migrates_legacy_custom_property_ids_in_order(self) -> None:
        first = self._custom_property()
        second = self._custom_property()
        config = UserCustomerAnalyticsConfig.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            user_id=self.user.id,
            pinned_custom_property_definition_ids=[second.id, first.id],
            properties={"future_setting": "kept"},
        )

        response = self.client.get(self.endpoint)

        expected = [
            {"kind": "custom_property", "id": str(second.id)},
            {"kind": "custom_property", "id": str(first.id)},
        ]
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        self.assertEqual(response.json(), {"pinned_properties": expected})
        config.refresh_from_db()
        self.assertEqual(config.properties, {"future_setting": "kept", "pinned_properties": expected})

    def test_patch_round_trips_heterogeneous_order_and_custom_projection(self) -> None:
        first_custom = self._custom_property()
        relationship = self._relationship()
        second_custom = self._custom_property()
        pinned_properties = [
            {"kind": "custom_property", "id": str(first_custom.id)},
            {"kind": "relationship", "id": str(relationship.id)},
            {"kind": "custom_property", "id": str(second_custom.id)},
        ]

        response = self.client.patch(self.endpoint, {"pinned_properties": pinned_properties}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        self.assertEqual(response.json(), {"pinned_properties": pinned_properties})
        self.assertEqual(self.client.get(self.endpoint).json(), {"pinned_properties": pinned_properties})
        config = UserCustomerAnalyticsConfig.objects.for_team(self.team.id).get(user_id=self.user.id)
        self.assertEqual(config.properties["pinned_properties"], pinned_properties)
        self.assertEqual(config.pinned_custom_property_definition_ids, [first_custom.id, second_custom.id])

        payload: dict[str, object] | None
        for payload in ({}, None):
            with self.subTest(payload=payload):
                unchanged = self.client.patch(self.endpoint, payload, format="json")
                self.assertEqual(unchanged.status_code, status.HTTP_200_OK, unchanged.json())
                self.assertEqual(unchanged.json(), {"pinned_properties": pinned_properties})
                self.assertEqual(self.client.get(self.endpoint).json(), {"pinned_properties": pinned_properties})

        cleared = self.client.patch(self.endpoint, {"pinned_properties": []}, format="json")

        self.assertEqual(cleared.status_code, status.HTTP_200_OK, cleared.json())
        self.assertEqual(cleared.json(), {"pinned_properties": []})
        config.refresh_from_db()
        self.assertEqual(config.properties["pinned_properties"], [])
        self.assertEqual(config.pinned_custom_property_definition_ids, [])

    def test_config_is_isolated_by_requesting_user_and_project(self) -> None:
        definition = self._custom_property()
        pinned = [{"kind": "custom_property", "id": str(definition.id)}]
        response = self.client.patch(self.endpoint, {"pinned_properties": pinned}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())

        other_user = User.objects.create_and_join(
            self.organization,
            "account-sidebar-other@example.com",
            "testtest",
        )
        self.client.force_login(other_user)
        self.assertEqual(self.client.get(self.endpoint).json(), {"pinned_properties": []})

        other_team = Team.objects.create(organization=self.organization, name="Other project")
        self.client.force_login(self.user)
        other_team_endpoint = f"/api/projects/{other_team.id}/user_customer_analytics_config/@me/"
        self.assertEqual(self.client.get(other_team_endpoint).json(), {"pinned_properties": []})

        self.assertEqual(
            UserCustomerAnalyticsConfig.objects.unscoped().filter(team_id=self.team.id, user_id=self.user.id).count(),
            1,
        )
        self.assertEqual(
            UserCustomerAnalyticsConfig.objects.unscoped().filter(team_id=self.team.id, user_id=other_user.id).count(),
            1,
        )
        self.assertEqual(
            UserCustomerAnalyticsConfig.objects.unscoped().filter(team_id=other_team.id, user_id=self.user.id).count(),
            1,
        )

    def test_environment_url_resolves_to_the_canonical_team(self) -> None:
        # `for_team` canonicalizes its filter but not the create kwargs, so an environment (child
        # team) id in the URL must resolve to the parent before the row is looked up or created.
        # A raw id makes the lookup never match and the unique constraint reject every later call.
        environment = Team.objects.create(organization=self.organization, parent_team=self.team, name="env")
        environment_endpoint = f"/api/projects/{environment.id}/user_customer_analytics_config/@me/"
        pinned = [{"kind": "custom_property", "id": str(self._custom_property().id)}]

        first = self.client.get(environment_endpoint)
        saved = self.client.patch(environment_endpoint, {"pinned_properties": pinned}, format="json")
        reread = self.client.get(environment_endpoint)

        self.assertEqual(first.status_code, status.HTTP_200_OK, first.json())
        self.assertEqual(saved.status_code, status.HTTP_200_OK, saved.json())
        self.assertEqual(reread.status_code, status.HTTP_200_OK, reread.json())
        self.assertEqual(reread.json(), {"pinned_properties": pinned})
        self.assertEqual(self.client.get(self.endpoint).json(), {"pinned_properties": pinned})
        config = UserCustomerAnalyticsConfig.objects.for_team(self.team.id).get(user_id=self.user.id)
        self.assertEqual(config.team_id, self.team.id)
        self.assertEqual(UserCustomerAnalyticsConfig.objects.unscoped().filter(user_id=self.user.id).count(), 1)

    def test_patch_rejects_invalid_references_on_the_pinned_properties_field(self) -> None:
        valid_custom = self._custom_property()
        person_custom = self._custom_property(target_type=TargetType.PERSON)
        relationship = self._relationship()
        other_team = Team.objects.create(organization=self.organization, name="Foreign project")
        foreign_custom = self._custom_property(team=other_team)
        valid_reference = {"kind": "custom_property", "id": str(valid_custom.id)}
        cases = [
            ("duplicates", [valid_reference, valid_reference], "duplicates"),
            ("wrong target", [{"kind": "custom_property", "id": str(person_custom.id)}], "account property"),
            ("relationship as custom", [{"kind": "custom_property", "id": str(relationship.id)}], "relationship"),
            ("custom as relationship", [{"kind": "relationship", "id": str(valid_custom.id)}], "custom property"),
            ("foreign team", [{"kind": "custom_property", "id": str(foreign_custom.id)}], "not found"),
            ("unknown", [{"kind": "relationship", "id": str(uuid4())}], "not found"),
            ("over limit", [valid_reference] * 51, "at most 50"),
        ]

        for label, pinned_properties, expected_detail in cases:
            with self.subTest(label):
                response = self.client.patch(
                    self.endpoint,
                    {"pinned_properties": pinned_properties},
                    format="json",
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json())
                self.assertEqual(response.json()["attr"], "pinned_properties")
                self.assertIn(expected_detail, response.json()["detail"])

        self.assertFalse(
            UserCustomerAnalyticsConfig.objects.unscoped().filter(team_id=self.team.id, user_id=self.user.id).exists()
        )

    @parameterized.expand(
        [
            ("personal", "account:read", status.HTTP_403_FORBIDDEN),
            ("personal", "account:write", status.HTTP_200_OK),
            ("oauth", "account:read", status.HTTP_403_FORBIDDEN),
            ("oauth", "account:write", status.HTTP_200_OK),
            ("personal", "account:write", status.HTTP_403_FORBIDDEN, "child_only"),
            ("personal", "account:write", status.HTTP_200_OK, "parent_and_child"),
            ("oauth", "account:write", status.HTTP_403_FORBIDDEN, "child_only"),
            ("oauth", "account:write", status.HTTP_200_OK, "parent_and_child"),
        ]
    )
    def test_token_requires_write_scope(
        self, kind: str, scope: str, expected_status: int, environment_scope: str | None = None
    ) -> None:
        pinned = [{"kind": "custom_property", "id": str(self._custom_property().id)}]
        self.client.patch(self.endpoint, {"pinned_properties": pinned}, format="json")
        endpoint = self.endpoint
        scoped_teams: list[int] = []
        if environment_scope:
            environment = Team.objects.create(organization=self.organization, parent_team=self.team)
            endpoint = f"/api/projects/{environment.id}/user_customer_analytics_config/@me/"
            scoped_teams = [environment.id] + ([self.team.id] if environment_scope == "parent_and_child" else [])
        if kind == "personal":
            token = generate_random_token_personal()
            PersonalAPIKey.objects.create(
                user=self.user,
                label="Sidebar test",
                secure_value=hash_key_value(token),
                scopes=[scope],
                scoped_teams=scoped_teams,
            )
        else:
            application = OAuthApplication.objects.create(
                name="Sidebar test",
                user=self.user,
                client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
                authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
                redirect_uris="https://example.com/callback",
                algorithm="RS256",
            )
            token = "pha_sidebar_test_token"
            OAuthAccessToken.objects.create(
                application=application,
                user=self.user,
                token=token,
                scope=scope,
                expires=timezone.now() + timedelta(hours=1),
                scoped_teams=scoped_teams,
            )
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        expected_read_status = status.HTTP_403_FORBIDDEN if environment_scope == "child_only" else status.HTTP_200_OK
        self.assertEqual(self.client.get(endpoint).status_code, expected_read_status)
        response = self.client.patch(endpoint, {"pinned_properties": []}, format="json")
        self.assertEqual(response.status_code, expected_status, response.json())
        expected_pins = [] if expected_status == status.HTTP_200_OK else pinned
        config = UserCustomerAnalyticsConfig.objects.for_team(self.team.id).get(user_id=self.user.id)
        self.assertEqual(config.properties["pinned_properties"], expected_pins)

    @parameterized.expand([("project",), ("customer_analytics",)])
    def test_child_access_does_not_grant_parent_access(self, resource: str) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        environment = Team.objects.create(organization=self.organization, parent_team=self.team)
        member = User.objects.create_and_join(self.organization, "child-member@example.com", "testtest")
        membership = OrganizationMembership.objects.get(user=member, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource=resource,
            resource_id=str(self.team.id) if resource == "project" else None,
            access_level="none",
            organization_member=membership,
        )
        AccessControl.objects.create(
            team=environment,
            resource=resource,
            resource_id=str(environment.id) if resource == "project" else None,
            access_level="member" if resource == "project" else "editor",
            organization_member=membership,
        )
        self.client.force_login(member)
        endpoint = f"/api/projects/{environment.id}/user_customer_analytics_config/@me/"
        self.assertEqual(self.client.get(endpoint).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            self.client.patch(endpoint, {"pinned_properties": []}, format="json").status_code, status.HTTP_403_FORBIDDEN
        )
        self.assertFalse(UserCustomerAnalyticsConfig.objects.for_team(self.team.id).filter(user_id=member.id).exists())

    def test_session_viewer_can_personalize_their_sidebar(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        viewer = User.objects.create_and_join(self.organization, "sidebar-viewer@example.com", "testtest")
        AccessControl.objects.create(
            team=self.team,
            resource="customer_analytics",
            resource_id=None,
            access_level="viewer",
            organization_member=OrganizationMembership.objects.get(user=viewer, organization=self.organization),
        )
        self.client.force_login(viewer)
        pinned = [{"kind": "custom_property", "id": str(self._custom_property().id)}]
        response = self.client.patch(self.endpoint, {"pinned_properties": pinned}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        self.assertEqual(self.client.get(self.endpoint).json(), {"pinned_properties": pinned})
