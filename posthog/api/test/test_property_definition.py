import json
from typing import Optional, Union
from unittest.mock import ANY, patch

from rest_framework import status

from posthog.models import (
    ActivityLog,
    EventDefinition,
    EventProperty,
    Organization,
    PropertyDefinition,
    Team,
)
from posthog.taxonomy.property_definition_api import PropertyDefinitionQuerySerializer, PropertyDefinitionViewSet
from posthog.test.base import APIBaseTest, BaseTest


class TestPropertyDefinitionAPI(APIBaseTest):
    EXPECTED_PROPERTY_DEFINITIONS: list[dict[str, Union[str, Optional[int], bool]]] = [
        {"name": "$browser", "is_numerical": False},
        {"name": "$current_url", "is_numerical": False},
        {"name": "$lib", "is_numerical": False},
        {"name": "$performance_raw", "is_numerical": False},
        {"name": "is_first_movie", "is_numerical": False},
        {"name": "app_rating", "is_numerical": True},
        {"name": "plan", "is_numerical": False},
        {"name": "purchase", "is_numerical": True},
        {"name": "purchase_value", "is_numerical": True},
        {"name": "first_visit", "is_numerical": False},
    ]

    def setUp(self) -> None:
        super().setUp()

        EventDefinition.objects.get_or_create(team=self.team, name="$pageview")

        PropertyDefinition.objects.get_or_create(team=self.team, name="$current_url")
        PropertyDefinition.objects.get_or_create(team=self.team, name="$lib")
        PropertyDefinition.objects.get_or_create(team=self.team, name="$browser")
        PropertyDefinition.objects.get_or_create(team=self.team, name="$performance_raw")
        PropertyDefinition.objects.get_or_create(team=self.team, name="first_visit")
        PropertyDefinition.objects.get_or_create(team=self.team, name="is_first_movie")
        PropertyDefinition.objects.get_or_create(team=self.team, name="app_rating", defaults={"is_numerical": True})
        PropertyDefinition.objects.get_or_create(team=self.team, name="plan")
        PropertyDefinition.objects.get_or_create(team=self.team, name="purchase_value", defaults={"is_numerical": True})
        PropertyDefinition.objects.get_or_create(team=self.team, name="purchase", defaults={"is_numerical": True})
        PropertyDefinition.objects.create(
            team=self.team, name="$initial_referrer", property_type="String"
        )  # We want to hide this property on events, but not on persons
        # We want to make sure that $session_entry_X properties are not returned
        PropertyDefinition.objects.get_or_create(team=self.team, name="$session_entry_utm_source")

        EventProperty.objects.get_or_create(team=self.team, event="$pageview", property="$browser")
        EventProperty.objects.get_or_create(team=self.team, event="$pageview", property="first_visit")
        EventProperty.objects.create(team=self.team, event="another_event", property="first_visit")

    def test_individual_property_formats(self):
        property = PropertyDefinition.objects.create(
            team=self.team, name="timestamp_property", property_type="DateTime"
        )
        response = self.client.get(f"/api/projects/{self.team.pk}/property_definitions/{property.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        assert response.json()["property_type"] == "DateTime"

    def test_list_property_definitions(self):
        response = self.client.get(f"/api/projects/{self.team.pk}/property_definitions/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], len(self.EXPECTED_PROPERTY_DEFINITIONS))

        self.assertEqual(len(response.json()["results"]), len(self.EXPECTED_PROPERTY_DEFINITIONS))

        for item in self.EXPECTED_PROPERTY_DEFINITIONS:
            response_item: dict = next(
                (_i for _i in response.json()["results"] if _i["name"] == item["name"]),
                {},
            )
            self.assertEqual(response_item["is_numerical"], item["is_numerical"])

    def test_list_property_definitions_with_excluded_properties(self):
        response = self.client.get(
            f'/api/projects/{self.team.pk}/property_definitions/?excluded_properties=["first_visit"]'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], len(self.EXPECTED_PROPERTY_DEFINITIONS) - 1)

        self.assertEqual(len(response.json()["results"]), len(self.EXPECTED_PROPERTY_DEFINITIONS) - 1)

    def test_list_property_definitions_with_excluded_core_properties(self):
        # core property that doesn't start with $
        PropertyDefinition.objects.get_or_create(team=self.team, name="utm_medium")

        response = self.client.get(f"/api/projects/{self.team.pk}/property_definitions/?exclude_core_properties=true")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 6)
        self.assertEqual(len(response.json()["results"]), 6)

    def test_list_numerical_property_definitions(self):
        response = self.client.get(f"/api/projects/{self.team.pk}/property_definitions/?is_numerical=true")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 3)

        self.assertEqual(len(response.json()["results"]), 3)
        properties = sorted([_i["name"] for _i in response.json()["results"]])

        self.assertEqual(properties, ["app_rating", "purchase", "purchase_value"])

    def test_pagination_of_property_definitions(self):
        PropertyDefinition.objects.bulk_create(
            [PropertyDefinition(team=self.team, name="z_property_{}".format(i)) for i in range(1, 301)]
        )
        expected_property_count = 310

        response = self.client.get(f"/api/projects/{self.team.pk}/property_definitions/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], expected_property_count)
        self.assertEqual(len(response.json()["results"]), 100)  # Default page size
        self.assertEqual(response.json()["results"][0]["name"], "$browser")
        self.assertEqual(
            response.json()["results"][1]["name"],
            "$current_url",
            [r["name"] for r in response.json()["results"]],
        )

        property_checkpoints = [
            180,
            270,
            90,
        ]  # Because Postgres's sorter does this: property_1; property_100, ..., property_2, property_200, ..., it's
        # easier to deterministically set the expected events

        for i in range(0, 3):
            response = self.client.get(response.json()["next"])
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            self.assertEqual(response.json()["count"], expected_property_count)
            self.assertEqual(
                len(response.json()["results"]), 100 if i < 2 else 10
            )  # Each page has 100 except the last one
            self.assertEqual(
                response.json()["results"][0]["name"],
                f"z_property_{property_checkpoints[i]}",
            )

    def test_cant_see_property_definitions_for_another_team(self):
        org = Organization.objects.create(name="Separate Org")
        team = Team.objects.create(organization=org, name="Default Project")
        team.event_properties = self.team.event_properties + [f"should_be_invisible_{i}" for i in range(0, 5)]
        team.save()

        response = self.client.get(f"/api/projects/{self.team.pk}/property_definitions/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for item in response.json()["results"]:
            self.assertNotIn("should_be_invisible", item["name"])

        # Also can't fetch for a team to which the user doesn't have permissions
        response = self.client.get(f"/api/projects/{team.pk}/property_definitions/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json(), self.permission_denied_response("You don't have access to the project."))

    def test_query_property_definitions(self):
        # no search at all
        response = self.client.get(f"/api/projects/{self.team.pk}/property_definitions")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        assert sorted([r["name"] for r in response_data["results"]]) == [
            "$browser",
            "$current_url",
            "$lib",
            "$performance_raw",
            "app_rating",
            "first_visit",
            "is_first_movie",
            "plan",
            "purchase",
            "purchase_value",
        ]

        # Regular search
        response = self.client.get(f"/api/projects/{self.team.pk}/property_definitions/?search=firs")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        assert [r["name"] for r in response_data["results"]] == [
            "first_visit",
            "is_first_movie",
        ]

        # Fuzzy search
        response = self.client.get(f"/api/projects/{self.team.pk}/property_definitions/?search=p ting")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["is_seen_on_filtered_events"], None)
        for item in response.json()["results"]:
            self.assertIn(item["name"], ["app_rating"])

        # Searching by alias
        response = self.client.get(f"/api/projects/{self.team.pk}/property_definitions/?search=ary")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["name"], "$lib")

        # Searching by alias with two parts
        response = self.client.get(f"/api/projects/{self.team.pk}/property_definitions/?search=brow%20perf")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["name"], "$performance_raw")

        # Searching from both a name and an alias
        response = self.client.get(f"/api/projects/{self.team.pk}/property_definitions/?search=brow")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 2)
        self.assertEqual(response.json()["results"][0]["name"], "$browser")  # uses name ilike 'brow'
        self.assertEqual(response.json()["results"][1]["name"], "$performance_raw")  # uses name in (...)

        # Handles URL encoding properly
        response = self.client.get(f"/api/projects/{self.team.pk}/property_definitions/?search=%24cur")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        for item in response.json()["results"]:
            self.assertIn(item["name"], ["$current_url"])

        # Shows properties belonging to queried event names
        response = self.client.get(
            "/api/projects/@current/property_definitions/?search=%24&event_names=%5B%22%24pageview%22%5D"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 4, response.json()["results"])
        self.assertEqual(response.json()["results"][0]["name"], "$browser")
        self.assertEqual(response.json()["results"][0]["is_seen_on_filtered_events"], True)
        self.assertEqual(response.json()["results"][1]["name"], "$current_url")
        self.assertEqual(response.json()["results"][1]["is_seen_on_filtered_events"], False)
        self.assertEqual(response.json()["results"][2]["name"], "$lib")
        self.assertEqual(response.json()["results"][2]["is_seen_on_filtered_events"], False)
        self.assertEqual(response.json()["results"][3]["name"], "$performance_raw")
        self.assertEqual(response.json()["results"][3]["is_seen_on_filtered_events"], False)

        # Fuzzy search 2
        response = self.client.get(f"/api/projects/{self.team.pk}/property_definitions/?search=hase%20")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(response.json()["count"], 2)
        for item in response.json()["results"]:
            self.assertIn(item["name"], ["purchase", "purchase_value"])

    def test_is_event_property_filter(self):
        response = self.client.get(f"/api/projects/{self.team.pk}/property_definitions/?search=firs")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        assert [r["name"] for r in response.json()["results"]] == [
            "first_visit",
            "is_first_movie",
        ]

        # specifying the event name doesn't filter the list,
        # instead it checks if the property has been seen with that event
        # previously it was necessary to _also_ send filter_by_event_names=(true or false) alongside the event name param
        response = self.client.get(
            f"/api/projects/{self.team.pk}/property_definitions/?event_names=%5B%22%24pageview%22%5D"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # sort a list of tuples by the first element

        assert sorted(
            [(r["name"], r["is_seen_on_filtered_events"]) for r in response.json()["results"]],
            key=lambda tup: tup[0],
        ) == [
            ("$browser", True),
            ("$current_url", False),
            ("$lib", False),
            ("$performance_raw", False),
            ("app_rating", False),
            ("first_visit", True),
            ("is_first_movie", False),
            ("plan", False),
            ("purchase", False),
            ("purchase_value", False),
        ]

        # get any properties that have been seen with $pageview event
        response = self.client.get(
            f"/api/projects/{self.team.pk}/property_definitions/?event_names=%5B%22%24pageview%22%5D&filter_by_event_names=true"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        assert sorted(
            [(r["name"], r["is_seen_on_filtered_events"]) for r in response.json()["results"]],
            key=lambda tup: tup[0],
        ) == [
            ("$browser", True),
            ("first_visit", True),
        ]

        # can combine the filters
        response = self.client.get(
            "/api/projects/@current/property_definitions/?search=firs&event_names=%5B%22%24pageview%22%5D&filter_by_event_names=true"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [(r["name"], r["is_seen_on_filtered_events"]) for r in response.json()["results"]],
            [("first_visit", True)],
        )

    def test_person_property_filter(self):
        PropertyDefinition.objects.create(
            team=self.team,
            name="event property",
            property_type="String",
            type=PropertyDefinition.Type.EVENT,
        )
        PropertyDefinition.objects.create(
            team=self.team,
            name="person property",
            property_type="String",
            type=PropertyDefinition.Type.PERSON,
        )
        PropertyDefinition.objects.create(
            team=self.team,
            name="$initial_referrer",
            property_type="String",
            type=PropertyDefinition.Type.PERSON,
        )  # We want to hide this property on events, but not on persons
        PropertyDefinition.objects.create(
            team=self.team,
            name="another",
            property_type="String",
            type=PropertyDefinition.Type.PERSON,
        )

        response = self.client.get(f"/api/projects/{self.team.pk}/property_definitions/?type=person")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [row["name"] for row in response.json()["results"]],
            [
                "$initial_referrer",
                "another",
                "person property",
                "$virt_initial_channel_type",
                "$virt_initial_referring_domain_type",
                "$virt_revenue",
                "$virt_revenue_last_30_days",
            ],
        )

        response = self.client.get(f"/api/projects/{self.team.pk}/property_definitions/?type=person&search=prop")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([row["name"] for row in response.json()["results"]], ["person property"])

        response = self.client.get(f"/api/projects/{self.team.pk}/property_definitions/?search=prop")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([row["name"] for row in response.json()["results"]], ["event property"])

        response = self.client.get(f"/api/projects/{self.team.pk}/property_definitions/?type=person&search=latest")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([row["name"] for row in response.json()["results"]], ["another", "person property"])

        response = self.client.get(f"/api/projects/{self.team.pk}/property_definitions/?type=person&search=late")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([row["name"] for row in response.json()["results"]], ["another", "person property"])

    def test_group_property_filter(self):
        PropertyDefinition.objects.create(
            team=self.team,
            name="group1 property",
            property_type="String",
            type=PropertyDefinition.Type.GROUP,
            group_type_index=1,
        )
        PropertyDefinition.objects.create(
            team=self.team,
            name="group1 another",
            property_type="String",
            type=PropertyDefinition.Type.GROUP,
            group_type_index=1,
        )
        PropertyDefinition.objects.create(
            team=self.team,
            name="group2 property",
            property_type="String",
            type=PropertyDefinition.Type.GROUP,
            group_type_index=2,
        )

        response = self.client.get(f"/api/projects/{self.team.pk}/property_definitions/?type=group&group_type_index=1")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [row["name"] for row in response.json()["results"]],
            ["group1 another", "group1 property"],
        )

        response = self.client.get(f"/api/projects/{self.team.pk}/property_definitions/?type=group&group_type_index=2")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([row["name"] for row in response.json()["results"]], ["group2 property"])

        response = self.client.get(
            f"/api/projects/{self.team.pk}/property_definitions/?type=group&search=prop&group_type_index=1"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([row["name"] for row in response.json()["results"]], ["group1 property"])

    def test_is_feature_flag_property_filter(self):
        PropertyDefinition.objects.create(team=self.team, name="$feature/plan", property_type="String")

        response = self.client.get(f"/api/projects/{self.team.pk}/property_definitions/?search=plan")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 2)

        response = self.client.get(
            f"/api/projects/{self.team.pk}/property_definitions/?search=plan&is_feature_flag=true"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["name"], "$feature/plan")

        response = self.client.get(
            f"/api/projects/{self.team.pk}/property_definitions/?search=plan&is_feature_flag=false"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["name"], "plan")

    @patch("posthoganalytics.capture")
    def test_delete_property_definition(self, mock_capture):
        property_definition = PropertyDefinition.objects.create(
            team=self.team, name="test_property", property_type="String"
        )
        response = self.client.delete(f"/api/projects/{self.team.pk}/property_definitions/{property_definition.id}")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(PropertyDefinition.objects.filter(id=property_definition.id).count(), 0)
        mock_capture.assert_called_once_with(
            event="property definition deleted",
            distinct_id=self.user.distinct_id,
            properties={"name": "test_property", "type": "event"},
            groups={
                "instance": ANY,
                "organization": str(self.organization.id),
                "project": str(self.team.uuid),
            },
        )

        activity_log: Optional[ActivityLog] = ActivityLog.objects.first()
        assert activity_log is not None
        assert activity_log.detail["type"] == "event"
        assert activity_log.item_id == str(property_definition.id)
        assert activity_log.detail["name"] == "test_property"
        assert activity_log.activity == "deleted"

    def test_event_name_filter_json_contains_int(self):
        event_name_json = json.dumps([1])
        response = self.client.get(f"/api/projects/{self.team.pk}/property_definitions/?event_names={event_name_json}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch("posthog.models.Organization.is_feature_available", return_value=False)
    def test_update_property_definition_without_taxonomy_entitlement(self, mock_is_feature_available):
        property_definition = PropertyDefinition.objects.create(
            team=self.team, name="test_property", property_type="String"
        )

        response = self.client.patch(
            f"/api/projects/{self.team.pk}/property_definitions/{property_definition.id}",
            {"property_type": "Numeric"},
        )

        assert response.status_code == status.HTTP_200_OK

        property_definition.refresh_from_db()
        assert property_definition.property_type == "Numeric"
        assert property_definition.is_numerical
        assert response.json()["property_type"] == "Numeric"

    @patch("posthog.models.Organization.is_feature_available", return_value=False)
    def test_update_property_definition_cannot_set_verified_without_entitlement(self, mock_is_feature_available):
        """Test that enterprise-only fields require license"""
        property_definition = PropertyDefinition.objects.create(
            team=self.team, name="test_property", property_type="String"
        )

        response = self.client.patch(
            f"/api/projects/{self.team.pk}/property_definitions/{property_definition.id}",
            {"verified": True},  # This should be blocked since it's enterprise-only
        )

        assert response.status_code == status.HTTP_402_PAYMENT_REQUIRED

    @patch("posthog.settings.EE_AVAILABLE", True)
    @patch("posthog.models.Organization.is_feature_available", return_value=True)
    def test_update_property_definition_with_taxonomy_entitlement(self, *mocks):
        property_definition = PropertyDefinition.objects.create(
            team=self.team, name="test_property", property_type="String"
        )

        response = self.client.patch(
            f"/api/projects/{self.team.pk}/property_definitions/{property_definition.id}",
            {"property_type": "Numeric", "verified": True},  # verified field only exists in enterprise serializer
        )

        assert response.status_code == status.HTTP_200_OK

        property_definition.refresh_from_db()
        assert property_definition.property_type == "Numeric"
        assert property_definition.is_numerical
        assert response.json()["property_type"] == "Numeric"

        # Verify the enterprise-only field was updated
        assert response.json()["verified"]

    def test_can_report_event_property_coexistence_when_custom_event_has_no_session_id(self) -> None:
        EventProperty.objects.create(team=self.team, event="$pageview", property="$session_id")

        response = self.client.get(
            f"/api/projects/{self.team.pk}/property_definitions/seen_together/?event_names=custom_event&event_names=$pageview&property_name=$session_id"
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"custom_event": False, "$pageview": True}

    def test_can_report_event_property_coexistence_when_custom_event_has_session_id(self) -> None:
        EventProperty.objects.create(team=self.team, event="custom_event", property="$session_id")

        response = self.client.get(
            f"/api/projects/{self.team.pk}/property_definitions/seen_together/?event_names=custom_event&event_names=$pageview&property_name=$session_id"
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json() == {"custom_event": True, "$pageview": False}

    def test_cannot_search_other_teams_properties(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Another Team")

        EventProperty.objects.create(team=other_team, event="custom_event", property="$session_id")

        response = self.client.get(
            f"/api/projects/{self.team.pk}/property_definitions/seen_together/?event_names=custom_event&event_names=$pageview&property_name=$session_id"
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"custom_event": False, "$pageview": False}

    def test_property_definition_project_id_coalesce(self):
        # Create legacy property with only team_id (old style)
        PropertyDefinition.objects.create(team=self.team, name="legacy_team_prop", property_type="String")
        # Create property with explicit project_id set (new style)
        PropertyDefinition.objects.create(
            team=self.team,
            project_id=self.team.pk,  # Explicitly set project_id
            name="newer_prop",
            property_type="String",
        )
        # Create property for another team to verify isolation
        other_team = Team.objects.create(organization=self.organization)
        PropertyDefinition.objects.create(team=other_team, name="other_team_prop", property_type="String")

        response = self.client.get(f"/api/projects/{self.project.id}/property_definitions/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Should return properties with either project_id or team_id matching
        property_names = {p["name"] for p in response.json()["results"]}
        self.assertIn("legacy_team_prop", property_names)  # Found via team_id
        self.assertIn("newer_prop", property_names)  # Found via project_id
        self.assertNotIn("other_team_prop", property_names)  # Different team, should not be found

    def test_property_definition_project_id_coalesce_detail(self):
        # Create legacy property with only team_id (old style)
        legacy_prop = PropertyDefinition.objects.create(team=self.team, name="legacy_team_prop", property_type="String")

        # Create property with explicit project_id set (new style)
        newer_prop = PropertyDefinition.objects.create(
            team=self.team,
            project_id=self.team.pk,  # Explicitly set project_id
            name="newer_prop",
            property_type="String",
        )

        # Create property for another team to verify isolation
        other_team = Team.objects.create(organization=self.organization)
        other_team_prop = PropertyDefinition.objects.create(
            team=other_team, name="other_team_prop", property_type="String"
        )

        # Test retrieving legacy property
        response = self.client.get(f"/api/projects/{self.project.id}/property_definitions/{legacy_prop.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["name"], "legacy_team_prop")

        # Test retrieving newer property
        response = self.client.get(f"/api/projects/{self.project.id}/property_definitions/{newer_prop.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["name"], "newer_prop")

        # Test retrieving other team's property should fail
        response = self.client.get(f"/api/projects/{self.project.id}/property_definitions/{other_team_prop.id}")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_virtual_property_numerical_filter(self):
        # Mock virtual properties to include some numerical ones
        with patch.object(
            PropertyDefinitionViewSet,
            "_BUILTIN_VIRTUAL_PERSON_PROPERTIES",
            [
                {
                    "id": "builtin_virt_initial_channel_type",
                    "name": "$virt_initial_channel_type",
                    "is_numerical": False,
                    "property_type": "String",
                    "tags": [],
                },
                {
                    "id": "builtin_virt_initial_referring_domain_type",
                    "name": "$virt_initial_referring_domain_type",
                    "is_numerical": False,
                    "property_type": "String",
                    "tags": [],
                },
                {
                    "id": "builtin_virt_session_count",
                    "name": "$virt_session_count",
                    "is_numerical": True,
                    "property_type": "Numeric",
                    "tags": [],
                },
                {
                    "id": "builtin_virt_pageview_count",
                    "name": "$virt_pageview_count",
                    "is_numerical": True,
                    "property_type": "Numeric",
                    "tags": [],
                },
                {
                    "id": "builtin_virt_revenue",
                    "name": "$virt_revenue",
                    "is_numerical": True,
                    "property_type": "Numeric",
                    "tags": [],
                },
                {
                    "id": "builtin_virt_revenue_last_30_days",
                    "name": "$virt_revenue_last_30_days",
                    "is_numerical": True,
                    "property_type": "Numeric",
                    "tags": [],
                },
            ],
        ):
            # Test numerical=true filter
            response = self.client.get(
                f"/api/projects/{self.team.pk}/property_definitions/?type=person&is_numerical=true"
            )
            assert response.status_code == status.HTTP_200_OK
            virtual_props = [prop for prop in response.json()["results"] if prop["name"].startswith("$virt_")]
            assert len(virtual_props) == 4
            assert all(prop["is_numerical"] for prop in virtual_props)
            assert all(
                prop["name"]
                in ["$virt_session_count", "$virt_pageview_count", "$virt_revenue", "$virt_revenue_last_30_days"]
                for prop in virtual_props
            )

            # Test numerical=false filter
            response = self.client.get(
                f"/api/projects/{self.team.pk}/property_definitions/?type=person&is_numerical=false"
            )
            assert response.status_code == status.HTTP_200_OK
            virtual_props = [prop for prop in response.json()["results"] if prop["name"].startswith("$virt_")]
            assert len(virtual_props) == 2
            assert all(not prop["is_numerical"] for prop in virtual_props)
            assert all(
                prop["name"] in ["$virt_initial_channel_type", "$virt_initial_referring_domain_type"]
                for prop in virtual_props
            )

    def test_virtual_property_feature_flag_filter_true(self):
        # Mock virtual properties to include some feature flag ones
        with patch.object(
            PropertyDefinitionViewSet,
            "_BUILTIN_VIRTUAL_PERSON_PROPERTIES",
            [
                {
                    "id": "builtin_virt_initial_channel_type",
                    "name": "$virt_initial_channel_type",
                    "is_numerical": False,
                    "property_type": "String",
                    "tags": [],
                },
                {
                    "id": "builtin_virt_feature_flag",
                    "name": "$feature/virt_flag",
                    "is_numerical": False,
                    "property_type": "String",
                    "tags": [],
                },
            ],
        ):
            # Test feature_flag=true filter
            response = self.client.get(
                f"/api/projects/{self.team.pk}/property_definitions/?type=person&is_feature_flag=true"
            )
            assert response.status_code == status.HTTP_200_OK
            virtual_props = [
                prop
                for prop in response.json()["results"]
                if prop["name"].startswith("$virt_") or prop["name"].startswith("$feature/")
            ]
            assert {p["name"] for p in virtual_props} == {"$feature/virt_flag"}

    def test_virtual_property_feature_flag_filter_false(self):
        # Mock virtual properties to include some feature flag ones
        with patch.object(
            PropertyDefinitionViewSet,
            "_BUILTIN_VIRTUAL_PERSON_PROPERTIES",
            [
                {
                    "id": "builtin_virt_initial_channel_type",
                    "name": "$virt_initial_channel_type",
                    "is_numerical": False,
                    "property_type": "String",
                    "tags": [],
                },
                {
                    "id": "builtin_virt_feature_flag",
                    "name": "$feature/virt_flag",
                    "is_numerical": False,
                    "property_type": "String",
                    "tags": [],
                },
            ],
        ):
            # Test feature_flag=false filter
            response = self.client.get(
                f"/api/projects/{self.team.pk}/property_definitions/?type=person&is_feature_flag=false"
            )
            assert response.status_code == status.HTTP_200_OK
            virtual_props = [
                prop
                for prop in response.json()["results"]
                if prop["name"].startswith("$virt_") or prop["name"].startswith("$feature/")
            ]
            assert {p["name"] for p in virtual_props} == {"$virt_initial_channel_type"}

    def test_virtual_property_hidden_filter(self):
        response = self.client.get(
            f"/api/projects/{self.team.pk}/property_definitions/?type=person&exclude_hidden=true"
        )
        assert response.status_code == status.HTTP_200_OK
        # Virtual properties should still be included when excluding hidden
        virtual_props = [prop for prop in response.json()["results"] if prop["name"].startswith("$virt_")]
        assert len(virtual_props) == 4

    def test_virtual_property_search_by_name(self):
        response = self.client.get(
            f"/api/projects/{self.team.pk}/property_definitions/?type=person&search=initial_channel"
        )
        assert response.status_code == status.HTTP_200_OK
        # Should find the virtual property by exact name
        assert any(prop["name"] == "$virt_initial_channel_type" for prop in response.json()["results"])

    def test_virtual_property_search_by_alias(self):
        response = self.client.get(f"/api/projects/{self.team.pk}/property_definitions/?type=person&search=channel")
        assert response.status_code == status.HTTP_200_OK
        # Should find the virtual property by alias
        assert any(prop["name"] == "$virt_initial_channel_type" for prop in response.json()["results"])

    def test_virtual_property_excluded_by_name(self):
        response = self.client.get(
            f'/api/projects/{self.team.pk}/property_definitions/?type=person&excluded_properties=["$virt_initial_channel_type"]'
        )
        assert response.status_code == status.HTTP_200_OK
        # Should exclude the specified virtual property
        assert not any(prop["name"] == "$virt_initial_channel_type" for prop in response.json()["results"])

    def test_virtual_property_excluded_by_core(self):
        response = self.client.get(
            f"/api/projects/{self.team.pk}/property_definitions/?type=person&exclude_core_properties=true"
        )
        assert response.status_code == status.HTTP_200_OK
        # Virtual properties should still be included when excluding core properties
        virtual_props = [prop for prop in response.json()["results"] if prop["name"].startswith("$virt_")]
        assert len(virtual_props) > 0

    def test_virtual_property_type_filter(self):
        response = self.client.get(f"/api/projects/{self.team.pk}/property_definitions/?type=person")
        assert response.status_code == status.HTTP_200_OK
        # Should include virtual properties when type=person
        virtual_props = [prop for prop in response.json()["results"] if prop["name"].startswith("$virt_")]
        assert len(virtual_props) > 0

        response = self.client.get(f"/api/projects/{self.team.pk}/property_definitions/?type=event")
        assert response.status_code == status.HTTP_200_OK
        # Should not include virtual properties when type=event
        virtual_props = [prop for prop in response.json()["results"] if prop["name"].startswith("$virt_")]
        assert len(virtual_props) == 0


class TestPropertyDefinitionQuerySerializer(BaseTest):
    def test_validation(self):
        assert PropertyDefinitionQuerySerializer(data={}).is_valid()
        assert PropertyDefinitionQuerySerializer(data={"type": "event", "event_names": '["foo","bar"]'}).is_valid()
        assert PropertyDefinitionQuerySerializer(data={"type": "person"}).is_valid()
        assert not PropertyDefinitionQuerySerializer(data={"type": "person", "event_names": '["foo","bar"]'}).is_valid()

        assert PropertyDefinitionQuerySerializer(data={"type": "group", "group_type_index": 3}).is_valid()
        assert not PropertyDefinitionQuerySerializer(data={"type": "group"}).is_valid()
        assert not PropertyDefinitionQuerySerializer(data={"type": "group", "group_type_index": 77}).is_valid()
        assert not PropertyDefinitionQuerySerializer(data={"type": "group", "group_type_index": -1}).is_valid()
        assert not PropertyDefinitionQuerySerializer(data={"type": "event", "group_type_index": 3}).is_valid()
