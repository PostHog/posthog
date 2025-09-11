import json
from typing import Optional, Union

from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import ANY, patch

from parameterized import parameterized
from rest_framework import status

from posthog.models import ActivityLog, EventDefinition, EventProperty, Organization, PropertyDefinition, Team
from posthog.taxonomy.property_definition_api import PropertyDefinitionQuerySerializer, PropertyDefinitionViewSet


class TestPropertyDefinitionAPI(APIBaseTest):
    EXPECTED_PROPERTY_DEFINITIONS: list[dict[str, Union[str, Optional[int], bool]]] = [
        {"name": "$browser", "is_numerical": False},
        {"name": "$current_url", "is_numerical": False},
        {"name": "$lib", "is_numerical": False},
        {"name": "$browser_version", "is_numerical": False},
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
        PropertyDefinition.objects.get_or_create(team=self.team, name="$browser_version")
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
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["property_type"] == "DateTime"

    def test_list_property_definitions(self):
        response = self.client.get(f"/api/projects/{self.team.pk}/property_definitions/")
        assert response.status_code == status.HTTP_200_OK

        assert response.json()["count"] == len(self.EXPECTED_PROPERTY_DEFINITIONS)

        assert [{"name": r["name"], "is_numerical": r["is_numerical"]} for r in response.json()["results"]] == sorted(
            self.EXPECTED_PROPERTY_DEFINITIONS, key=lambda x: str(x["name"])
        )

    def test_list_property_definitions_with_excluded_properties(self):
        response = self.client.get(
            f'/api/projects/{self.team.pk}/property_definitions/?excluded_properties=["first_visit"]'
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == len(self.EXPECTED_PROPERTY_DEFINITIONS) - 1

        assert "first_visit" not in [r["name"] for r in response.json()["results"]]

    def test_list_property_definitions_with_excluded_core_properties(self):
        # core property that doesn't start with $
        PropertyDefinition.objects.get_or_create(team=self.team, name="utm_medium")

        response = self.client.get(f"/api/projects/{self.team.pk}/property_definitions/?exclude_core_properties=true")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == 6
        assert len(response.json()["results"]) == 6

    def test_list_numerical_property_definitions(self):
        response = self.client.get(f"/api/projects/{self.team.pk}/property_definitions/?is_numerical=true")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == 3

        assert sorted([_i["name"] for _i in response.json()["results"]]) == ["app_rating", "purchase", "purchase_value"]

    def test_pagination_of_property_definitions(self):
        PropertyDefinition.objects.bulk_create(
            [PropertyDefinition(team=self.team, name="z_property_{}".format(i)) for i in range(1, 301)]
        )
        expected_property_count = 310

        response = self.client.get(f"/api/projects/{self.team.pk}/property_definitions/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == expected_property_count
        assert len(response.json()["results"]) == 100  # Default page size
        assert response.json()["results"][0]["name"] == "$browser"
        assert response.json()["results"][1]["name"] == "$browser_version"

        property_checkpoints = [
            180,
            270,
            90,
        ]  # Because Postgres's sorter does this: property_1; property_100, ..., property_2, property_200, ..., it's
        # easier to deterministically set the expected events

        for i in range(0, 3):
            response = self.client.get(response.json()["next"])
            assert response.status_code == status.HTTP_200_OK

            assert response.json()["count"] == expected_property_count
            assert len(response.json()["results"]) == (100 if i < 2 else 10)  # Each page has 100 except the last one
            assert response.json()["results"][0]["name"] == f"z_property_{property_checkpoints[i]}"

    def test_cant_see_property_definitions_for_another_team(self):
        org = Organization.objects.create(name="Separate Org")
        team = Team.objects.create(organization=org, name="Default Project")
        team.event_properties = self.team.event_properties + [f"should_be_invisible_{i}" for i in range(0, 5)]
        team.save()

        response = self.client.get(f"/api/projects/{self.team.pk}/property_definitions/")
        assert response.status_code == status.HTTP_200_OK
        for item in response.json()["results"]:
            assert "should_be_invisible" not in item["name"]

        # Also can't fetch for a team to which the user doesn't have permissions
        response = self.client.get(f"/api/projects/{team.pk}/property_definitions/")
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json() == self.permission_denied_response("You don't have access to the project.")

    def test_list_all_property_definitions_without_search(self):
        response = self.client.get(f"/api/projects/{self.team.pk}/property_definitions")
        assert response.status_code == status.HTTP_200_OK

        assert sorted([r["name"] for r in response.json()["results"]]) == sorted(
            [
                "$browser",
                "$browser_version",
                "$current_url",
                "$lib",
                "app_rating",
                "first_visit",
                "is_first_movie",
                "plan",
                "purchase",
                "purchase_value",
            ]
        )

    @parameterized.expand(
        [
            ("Searching for properties starting with 'firs'", "firs", ["first_visit", "is_first_movie"]),
            ("Fuzzy search: 'p ting' matches 'app_rating'", "p ting", ["app_rating"]),
            ("Alias search: 'ary' matches '$lib' (library)", "ary", ["$lib"]),
            ("Alias search: 'brow ver' matches '$browser_version'", "brow ver", ["$browser_version"]),
            ("URL-encoded search for properties starting with '$cur'", "$cur", ["$current_url"]),
            ("Fuzzy search: 'hase ' matches properties containing 'chase'", "hase ", ["purchase", "purchase_value"]),
            ("Search matching multiple properties", "brow", ["$browser", "$browser_version"]),
        ]
    )
    def test_property_search_returns_expected_results(
        self, _name: str, search_term: str, expected_property_names: list[str]
    ) -> None:
        response = self.client.get(f"/api/projects/{self.team.pk}/property_definitions/?search={search_term}")
        assert response.status_code == status.HTTP_200_OK

        assert [prop["name"] for prop in response.json()["results"]] == expected_property_names

        if search_term == "p ting":
            assert response.json()["results"][0]["is_seen_on_filtered_events"] is None

    def test_property_search_with_event_filter_shows_event_association(self):
        # URL params: search=$ and event_names=["$pageview"]
        response = self.client.get(
            "/api/projects/@current/property_definitions/?search=%24&event_names=%5B%22%24pageview%22%5D"
        )
        assert response.status_code == status.HTTP_200_OK

        actual_results = [(r["name"], r["is_seen_on_filtered_events"]) for r in response.json()["results"]]

        assert actual_results == [
            ("$browser", True),
            ("$browser_version", False),
            ("$current_url", False),
            ("$lib", False),
        ]

    def test_is_event_property_filter(self):
        response = self.client.get(f"/api/projects/{self.team.pk}/property_definitions/?search=firs")
        assert response.status_code == status.HTTP_200_OK
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
        assert response.status_code == status.HTTP_200_OK

        assert sorted(
            [(r["name"], r["is_seen_on_filtered_events"]) for r in response.json()["results"]],
            key=lambda tup: tup[0],
        ) == [
            ("$browser", True),
            ("$browser_version", False),
            ("$current_url", False),
            ("$lib", False),
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
        assert response.status_code == status.HTTP_200_OK
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
        assert response.status_code == status.HTTP_200_OK
        assert [(r["name"], r["is_seen_on_filtered_events"]) for r in response.json()["results"]] == [
            ("first_visit", True)
        ]

    def test_person_property_filter_setup(self):
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

    @parameterized.expand(
        [
            (
                "Get all person properties",
                "type=person",
                [
                    "$initial_referrer",
                    "another",
                    "person property",
                    "$virt_initial_channel_type",
                    "$virt_initial_referring_domain_type",
                    "$virt_revenue",
                    "$virt_revenue_last_30_days",
                ],
            ),
            ("Search person properties containing 'prop'", "type=person&search=prop", ["person property"]),
            ("Search all properties containing 'prop'", "search=prop", ["event property"]),
            (
                "Search person properties containing 'latest'",
                "type=person&search=latest",
                ["another", "person property"],
            ),
            ("Search person properties containing 'late'", "type=person&search=late", ["another", "person property"]),
        ]
    )
    def test_person_property_filters(self, _name: str, query_params: str, expected_results: list[str]) -> None:
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

        response = self.client.get(f"/api/projects/{self.team.pk}/property_definitions/?{query_params}")
        assert response.status_code == status.HTTP_200_OK

        assert [row["name"] for row in response.json()["results"]] == expected_results

    @parameterized.expand(
        [
            (
                "Get all group1 properties",
                "type=group&group_type_index=1",
                ["group1 another", "group1 property", "$virt_revenue", "$virt_revenue_last_30_days"],
            ),
            (
                "Get all group2 properties",
                "type=group&group_type_index=2",
                ["group2 property", "$virt_revenue", "$virt_revenue_last_30_days"],
            ),
            (
                "Search group1 properties containing 'prop'",
                "type=group&search=prop&group_type_index=1",
                ["group1 property"],
            ),
        ]
    )
    def test_group_property_filter(self, _name: str, query_params: str, expected_results: list[str]) -> None:
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

        response = self.client.get(f"/api/projects/{self.team.pk}/property_definitions/?{query_params}")
        assert response.status_code == status.HTTP_200_OK
        assert [row["name"] for row in response.json()["results"]] == expected_results

    @parameterized.expand(
        [
            ("Search for 'plan' without filter", "search=plan", 2, None),
            ("Search for 'plan' feature flags only", "search=plan&is_feature_flag=true", 1, ["$feature/plan"]),
            ("Search for 'plan' non-feature flags only", "search=plan&is_feature_flag=false", 1, ["plan"]),
        ]
    )
    def test_feature_flag_property_filter(
        self, _name: str, query_params: str, expected_count: int, expected_names: list[str] | None
    ) -> None:
        PropertyDefinition.objects.create(team=self.team, name="$feature/plan", property_type="String")

        response = self.client.get(f"/api/projects/{self.team.pk}/property_definitions/?{query_params}")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == expected_count

        if expected_names:
            assert [r["name"] for r in response.json()["results"]] == expected_names

    @patch("posthoganalytics.capture")
    def test_delete_property_definition(self, mock_capture):
        property_definition = PropertyDefinition.objects.create(
            team=self.team, name="test_property", property_type="String"
        )
        response = self.client.delete(f"/api/projects/{self.team.pk}/property_definitions/{property_definition.id}")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert PropertyDefinition.objects.filter(id=property_definition.id).count() == 0
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

        activity_log: Optional[ActivityLog] = ActivityLog.objects.filter(
            scope="PropertyDefinition", activity="deleted"
        ).first()
        assert activity_log is not None
        assert activity_log.detail["type"] == "event"
        assert activity_log.item_id == str(property_definition.id)
        assert activity_log.detail["name"] == "test_property"
        assert activity_log.activity == "deleted"

    def test_event_name_filter_json_contains_int(self):
        event_name_json = json.dumps([1])
        response = self.client.get(f"/api/projects/{self.team.pk}/property_definitions/?event_names={event_name_json}")
        assert response.status_code == status.HTTP_200_OK

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

    @parameterized.expand(
        [
            (
                "Event property coexistence when custom event has no session_id",
                lambda self: EventProperty.objects.create(team=self.team, event="$pageview", property="$session_id"),
                {"custom_event": False, "$pageview": True},
            ),
            (
                "Event property coexistence when custom event has session_id",
                lambda self: EventProperty.objects.create(team=self.team, event="custom_event", property="$session_id"),
                {"custom_event": True, "$pageview": False},
            ),
            (
                "Cannot search other teams properties",
                lambda self: EventProperty.objects.create(
                    team=Team.objects.create(organization=self.organization, name="Another Team"),
                    event="custom_event",
                    property="$session_id",
                ),
                {"custom_event": False, "$pageview": False},
            ),
        ]
    )
    def test_event_property_coexistence(self, _name: str, setup_func, expected_results: dict[str, bool]) -> None:
        setup_func(self)

        response = self.client.get(
            f"/api/projects/{self.team.pk}/property_definitions/seen_together/?event_names=custom_event&event_names=$pageview&property_name=$session_id"
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == expected_results

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
        assert response.status_code == status.HTTP_200_OK

        # Should return properties with either project_id or team_id matching
        property_names = {p["name"] for p in response.json()["results"]}
        assert "legacy_team_prop" in property_names  # Found via team_id
        assert "newer_prop" in property_names  # Found via project_id
        assert "other_team_prop" not in property_names  # Different team, should not be found

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
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == "legacy_team_prop"

        # Test retrieving newer property
        response = self.client.get(f"/api/projects/{self.project.id}/property_definitions/{newer_prop.id}")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == "newer_prop"

        # Test retrieving other team's property should fail
        response = self.client.get(f"/api/projects/{self.project.id}/property_definitions/{other_team_prop.id}")
        assert response.status_code == status.HTTP_404_NOT_FOUND

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

    @parameterized.expand(
        [
            # (test_name, is_feature_flag, expected_virtual_props)
            ("Filter virtual properties that are feature flags", "true", {"$feature/virt_flag"}),
            ("Filter virtual properties that are not feature flags", "false", {"$virt_initial_channel_type"}),
        ]
    )
    def test_virtual_property_feature_flag_filter(
        self, _name: str, is_feature_flag: str, expected_virtual_props: set[str]
    ) -> None:
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
            response = self.client.get(
                f"/api/projects/{self.team.pk}/property_definitions/?type=person&is_feature_flag={is_feature_flag}"
            )
            assert response.status_code == status.HTTP_200_OK
            virtual_props = [
                prop
                for prop in response.json()["results"]
                if prop["name"].startswith("$virt_") or prop["name"].startswith("$feature/")
            ]
            assert {p["name"] for p in virtual_props} == expected_virtual_props

    def test_virtual_property_hidden_filter(self):
        response = self.client.get(
            f"/api/projects/{self.team.pk}/property_definitions/?type=person&exclude_hidden=true"
        )
        assert response.status_code == status.HTTP_200_OK
        # Virtual properties should still be included when excluding hidden
        virtual_props = [prop for prop in response.json()["results"] if prop["name"].startswith("$virt_")]
        assert len(virtual_props) == 4

    @parameterized.expand(
        [
            # (test_name, search_term, expected_property_name, search_type)
            ("Search by exact name", "initial_channel", "$virt_initial_channel_type", "name search"),
            ("Search by alias", "channel", "$virt_initial_channel_type", "alias search"),
        ]
    )
    def test_virtual_property_search(
        self, _name: str, search_term: str, expected_property_name: str, _search_type: str
    ) -> None:
        response = self.client.get(
            f"/api/projects/{self.team.pk}/property_definitions/?type=person&search={search_term}"
        )
        assert response.status_code == status.HTTP_200_OK
        # Should find the virtual property
        assert any(prop["name"] == expected_property_name for prop in response.json()["results"])

    def test_virtual_property_excluded_by_name(self):
        response = self.client.get(
            f'/api/projects/{self.team.pk}/property_definitions/?type=person&excluded_properties=["$virt_initial_channel_type"]'
        )
        assert response.status_code == status.HTTP_200_OK
        # Should exclude the specified virtual property
        assert not any(prop["name"] == "$virt_initial_channel_type" for prop in response.json()["results"])

        response = self.client.get(
            f'/api/projects/{self.team.pk}/property_definitions/?type=group&group_type_index=0&excluded_properties=["$virt_revenue"]'
        )
        assert response.status_code == status.HTTP_200_OK
        # Should exclude the specified virtual property
        assert not any(prop["name"] == "$virt_revenue" for prop in response.json()["results"])

    def test_virtual_property_excluded_by_core(self):
        response = self.client.get(
            f"/api/projects/{self.team.pk}/property_definitions/?type=person&exclude_core_properties=true"
        )
        assert response.status_code == status.HTTP_200_OK
        # Virtual properties should still be included when excluding core properties
        virtual_props = [prop for prop in response.json()["results"] if prop["name"].startswith("$virt_")]
        assert len(virtual_props) > 0

        response = self.client.get(
            f"/api/projects/{self.team.pk}/property_definitions/?type=group&group_type_index=0&exclude_core_properties=true"
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

        response = self.client.get(f"/api/projects/{self.team.pk}/property_definitions/?type=group&group_type_index=0")
        assert response.status_code == status.HTTP_200_OK
        # Should include virtual properties when type=group
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
