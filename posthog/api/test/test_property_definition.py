from typing import Dict, List, Optional, Union

from rest_framework import status

from posthog.api.property_definition import PropertyDefinitionQuerySerializer
from posthog.models import EventDefinition, EventProperty, Organization, PropertyDefinition, Team
from posthog.test.base import APIBaseTest, BaseTest


class TestPropertyDefinitionAPI(APIBaseTest):

    EXPECTED_PROPERTY_DEFINITIONS: List[Dict[str, Union[str, Optional[int], bool]]] = [
        {"name": "$browser", "query_usage_30_day": None, "is_numerical": False},
        {"name": "$current_url", "query_usage_30_day": 3, "is_numerical": False},
        {"name": "is_first_movie", "query_usage_30_day": None, "is_numerical": False},
        {"name": "app_rating", "query_usage_30_day": 1, "is_numerical": True},
        {"name": "plan", "query_usage_30_day": 1, "is_numerical": False},
        {"name": "purchase", "query_usage_30_day": None, "is_numerical": True},
        {"name": "purchase_value", "query_usage_30_day": None, "is_numerical": True},
        {"name": "first_visit", "query_usage_30_day": None, "is_numerical": False},
    ]

    def setUp(self) -> None:
        super().setUp()

        EventDefinition.objects.get_or_create(team=self.team, name="$pageview")

        PropertyDefinition.objects.get_or_create(
            team=self.team, name="$current_url", defaults={"query_usage_30_day": 3}
        )
        PropertyDefinition.objects.get_or_create(team=self.team, name="$browser")
        PropertyDefinition.objects.get_or_create(team=self.team, name="first_visit")
        PropertyDefinition.objects.get_or_create(team=self.team, name="is_first_movie")
        PropertyDefinition.objects.get_or_create(
            team=self.team, name="app_rating", defaults={"query_usage_30_day": 1, "is_numerical": True}
        )
        PropertyDefinition.objects.get_or_create(team=self.team, name="plan", defaults={"query_usage_30_day": 1})
        PropertyDefinition.objects.get_or_create(team=self.team, name="purchase_value", defaults={"is_numerical": True})
        PropertyDefinition.objects.get_or_create(team=self.team, name="purchase", defaults={"is_numerical": True})

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
            response_item: Dict = next((_i for _i in response.json()["results"] if _i["name"] == item["name"]), {})
            self.assertEqual(response_item["query_usage_30_day"], item["query_usage_30_day"], item)
            self.assertEqual(response_item["is_numerical"], item["is_numerical"])

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

        response = self.client.get(f"/api/projects/{self.team.pk}/property_definitions/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 308)
        self.assertEqual(len(response.json()["results"]), 100)  # Default page size
        self.assertEqual(
            response.json()["results"][0]["name"], "$current_url", [r["name"] for r in response.json()["results"]]
        )

        property_checkpoints = [
            182,
            272,
            92,
        ]  # Because Postgres's sorter does this: property_1; property_100, ..., property_2, property_200, ..., it's
        # easier to deterministically set the expected events

        for i in range(0, 3):
            response = self.client.get(response.json()["next"])
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            self.assertEqual(response.json()["count"], 308)
            self.assertEqual(
                len(response.json()["results"]), 100 if i < 2 else 8
            )  # Each page has 100 except the last one
            self.assertEqual(response.json()["results"][0]["name"], f"z_property_{property_checkpoints[i]}")

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
        self.assertEqual(response.json(), self.permission_denied_response())

    def test_query_property_definitions(self):
        # no search at all
        response = self.client.get(f"/api/projects/{self.team.pk}/property_definitions")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        assert sorted([r["name"] for r in response_data["results"]]) == [
            "$browser",
            "$current_url",
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
        assert [r["name"] for r in response_data["results"]] == ["first_visit", "is_first_movie"]

        # Fuzzy search
        response = self.client.get(f"/api/projects/{self.team.pk}/property_definitions/?search=p ting")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["is_seen_on_filtered_events"], None)
        for item in response.json()["results"]:
            self.assertIn(item["name"], ["app_rating"])

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
        self.assertEqual(response.json()["count"], 2, response.json()["results"])
        self.assertEqual(response.json()["results"][0]["name"], "$browser")
        self.assertEqual(response.json()["results"][0]["is_seen_on_filtered_events"], True)
        self.assertEqual(response.json()["results"][1]["name"], "$current_url")
        self.assertEqual(response.json()["results"][1]["is_seen_on_filtered_events"], False)

        # Fuzzy search 2
        response = self.client.get(f"/api/projects/{self.team.pk}/property_definitions/?search=hase%20")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(response.json()["count"], 2)
        for item in response.json()["results"]:
            self.assertIn(item["name"], ["purchase", "purchase_value"])

    def test_is_event_property_filter(self):
        response = self.client.get(f"/api/projects/{self.team.pk}/property_definitions/?search=firs")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        assert [r["name"] for r in response.json()["results"]] == ["first_visit", "is_first_movie"]

        # specifying the event name doesn't filter the list,
        # instead it checks if the property has been seen with that event
        # previously it was necessary to _also_ send filter_by_event_names=(true or false) alongside the event name param
        response = self.client.get(
            f"/api/projects/{self.team.pk}/property_definitions/?event_names=%5B%22%24pageview%22%5D"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # sort a list of tuples by the first element

        assert sorted(
            [(r["name"], r["is_seen_on_filtered_events"]) for r in response.json()["results"]], key=lambda tup: tup[0]
        ) == [
            ("$browser", True),
            ("$current_url", False),
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
            [(r["name"], r["is_seen_on_filtered_events"]) for r in response.json()["results"]], key=lambda tup: tup[0]
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
            [(r["name"], r["is_seen_on_filtered_events"]) for r in response.json()["results"]], [("first_visit", True)]
        )

    def test_person_property_filter(self):
        PropertyDefinition.objects.create(
            team=self.team, name="event property", property_type="String", type=PropertyDefinition.Type.EVENT
        )
        PropertyDefinition.objects.create(
            team=self.team, name="person property", property_type="String", type=PropertyDefinition.Type.PERSON
        )
        PropertyDefinition.objects.create(
            team=self.team, name="another", property_type="String", type=PropertyDefinition.Type.PERSON
        )

        response = self.client.get(f"/api/projects/{self.team.pk}/property_definitions/?type=person")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([row["name"] for row in response.json()["results"]], ["another", "person property"])

        response = self.client.get(f"/api/projects/{self.team.pk}/property_definitions/?type=person&search=prop")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([row["name"] for row in response.json()["results"]], ["person property"])

        response = self.client.get(f"/api/projects/{self.team.pk}/property_definitions/?search=prop")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([row["name"] for row in response.json()["results"]], ["event property"])

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
        self.assertEqual([row["name"] for row in response.json()["results"]], ["group1 another", "group1 property"])

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
