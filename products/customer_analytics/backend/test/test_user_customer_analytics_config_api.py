from uuid import uuid4

from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models.team import Team
from posthog.models.user import User

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
