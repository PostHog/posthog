import urllib.parse
from typing import cast

import pytest
from django.db.utils import IntegrityError
from django.utils import timezone
from rest_framework import status

from ee.models.license import License, LicenseManager
from ee.models.property_definition import EnterprisePropertyDefinition
from posthog.models import EventProperty, Tag
from posthog.models.property_definition import PropertyDefinition
from posthog.test.base import APIBaseTest


class TestPropertyDefinitionEnterpriseAPI(APIBaseTest):
    def test_can_set_and_query_property_type_and_format(self):
        property = EnterprisePropertyDefinition.objects.create(
            team=self.team, name="a timestamp", property_type="DateTime",
        )
        response = self.client.get(f"/api/projects/@current/property_definitions/{property.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        assert response.json()["property_type"] == "DateTime"

        query_list_response = self.client.get(f"/api/projects/@current/property_definitions")
        self.assertEqual(query_list_response.status_code, status.HTTP_200_OK)
        matches = [p["name"] for p in query_list_response.json()["results"] if p["name"] == "a timestamp"]
        assert len(matches) == 1

    def test_errors_on_invalid_property_type(self):
        with pytest.raises(IntegrityError):
            EnterprisePropertyDefinition.objects.create(
                team=self.team, name="a timestamp", property_type="not an allowed option",
            )

    def test_retrieve_existing_property_definition(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2500, 1, 19, 3, 14, 7)
        )
        property = EnterprisePropertyDefinition.objects.create(team=self.team, name="enterprise property")
        tag = Tag.objects.create(name="deprecated", team_id=self.team.id)
        property.tagged_items.create(tag_id=tag.id)
        response = self.client.get(f"/api/projects/@current/property_definitions/{property.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(response_data["name"], "enterprise property")
        self.assertEqual(response_data["description"], "")
        self.assertEqual(response_data["tags"], ["deprecated"])

    def test_retrieve_create_property_definition(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2500, 1, 19, 3, 14, 7)
        )
        property = PropertyDefinition.objects.create(team=self.team, name="property")
        response = self.client.get(f"/api/projects/@current/property_definitions/{property.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        enterprise_property = EnterprisePropertyDefinition.objects.all().first()
        property.refresh_from_db()
        self.assertEqual(enterprise_property.propertydefinition_ptr_id, property.id)  # type: ignore
        self.assertEqual(enterprise_property.name, property.name)  # type: ignore
        self.assertEqual(enterprise_property.team.id, property.team.id)  # type: ignore

    def test_search_property_definition(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2500, 1, 19, 3, 14, 7)
        )
        tag = Tag.objects.create(name="deprecated", team_id=self.team.id)
        EventProperty.objects.create(team=self.team, event="$pageview", property="enterprise property")
        enterprise_property = EnterprisePropertyDefinition.objects.create(
            team=self.team, name="enterprise property", description=""
        )
        enterprise_property.tagged_items.create(tag_id=tag.id)
        other_property = EnterprisePropertyDefinition.objects.create(
            team=self.team, name="other property", description=""
        )
        other_property.tagged_items.create(tag_id=tag.id)
        set_property = EnterprisePropertyDefinition.objects.create(team=self.team, name="$set", description="")
        set_property.tagged_items.create(tag_id=tag.id)

        response = self.client.get(f"/api/projects/@current/property_definitions/?search=enter")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(len(response_data["results"]), 1)

        self.assertEqual(response_data["results"][0]["name"], "enterprise property")
        self.assertEqual(response_data["results"][0]["description"], "")
        self.assertEqual(response_data["results"][0]["tags"], ["deprecated"])

        response = self.client.get(f"/api/projects/@current/property_definitions/?search=enterprise")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(len(response_data["results"]), 1)
        # always True if not scoping by event names
        self.assertEqual(response_data["results"][0]["is_event_property"], None)

        # add event_names=['$pageview'] to get properties that have been seen by this event
        response = self.client.get(
            f"/api/projects/@current/property_definitions/?search=property&event_names=%5B%22%24pageview%22%5D"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(len(response_data["results"]), 2)
        self.assertEqual(response_data["results"][0]["name"], "enterprise property")
        self.assertEqual(response_data["results"][0]["is_event_property"], True)
        self.assertEqual(response_data["results"][1]["name"], "other property")
        self.assertEqual(response_data["results"][1]["is_event_property"], False)

        response = self.client.get(f"/api/projects/@current/property_definitions/?search=er pr")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(len(response_data["results"]), 2)

        response = self.client.get(f"/api/projects/@current/property_definitions/?search=bust")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(len(response_data["results"]), 0)

        response = self.client.get(f"/api/projects/@current/property_definitions/?search=set")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(len(response_data["results"]), 0)

        response = self.client.get(f"/api/projects/@current/property_definitions/?search=")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(len(response_data["results"]), 2)

    def test_update_property_definition(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2038, 1, 19, 3, 14, 7)
        )
        property = EnterprisePropertyDefinition.objects.create(team=self.team, name="enterprise property")
        response = self.client.patch(
            f"/api/projects/@current/property_definitions/{str(property.id)}/",
            {"description": "This is a description.", "tags": ["official", "internal"],},
        )
        response_data = response.json()
        self.assertEqual(response_data["description"], "This is a description.")
        self.assertEqual(response_data["updated_by"]["first_name"], self.user.first_name)
        self.assertEqual(set(response_data["tags"]), {"official", "internal"})

        property.refresh_from_db()
        self.assertEqual(set(property.tagged_items.values_list("tag__name", flat=True)), {"official", "internal"})

    def test_update_property_without_license(self):
        property = EnterprisePropertyDefinition.objects.create(team=self.team, name="enterprise property")
        response = self.client.patch(
            f"/api/projects/@current/property_definitions/{str(property.id)}/", data={"description": "test"},
        )
        self.assertEqual(response.status_code, status.HTTP_402_PAYMENT_REQUIRED)
        self.assertIn("This feature is part of the premium PostHog offering.", response.json()["detail"])

    def test_with_expired_license(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2010, 1, 19, 3, 14, 7)
        )
        property = EnterprisePropertyDefinition.objects.create(team=self.team, name="description test")
        response = self.client.patch(
            f"/api/projects/@current/property_definitions/{str(property.id)}/", data={"description": "test"},
        )
        self.assertEqual(response.status_code, status.HTTP_402_PAYMENT_REQUIRED)
        self.assertIn("This feature is part of the premium PostHog offering.", response.json()["detail"])

    def test_filter_property_definitions(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2500, 1, 19, 3, 14, 7)
        )
        EnterprisePropertyDefinition.objects.create(team=self.team, name="plan")
        EnterprisePropertyDefinition.objects.create(team=self.team, name="purchase")
        EnterprisePropertyDefinition.objects.create(team=self.team, name="app_rating")

        response = self.client.get("/api/projects/@current/property_definitions/?properties=plan,app_rating")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(response.json()["count"], 2)
        for item in response.json()["results"]:
            self.assertIn(item["name"], ["plan", "app_rating"])

    def test_event_property_definition_no_duplicate_tags(self):
        from ee.models.license import License, LicenseManager

        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            key="key_123", plan="enterprise", valid_until=timezone.datetime(2038, 1, 19, 3, 14, 7), max_users=3,
        )
        property = EnterprisePropertyDefinition.objects.create(team=self.team, name="description test")
        response = self.client.patch(
            f"/api/projects/@current/property_definitions/{str(property.id)}/", data={"tags": ["a", "b", "a"]},
        )

        self.assertListEqual(sorted(response.json()["tags"]), ["a", "b"])

    def test_order_ids_first_filter(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2010, 1, 19, 3, 14, 7)
        )
        # is_first_movie, first_visit
        is_first_movie_property = EnterprisePropertyDefinition.objects.create(team=self.team, name="is_first_movie")
        first_visit_property = EnterprisePropertyDefinition.objects.create(team=self.team, name="first_visit")
        ids = [is_first_movie_property.id, first_visit_property.id]

        response = self.client.get("/api/projects/@current/property_definitions/?search=firs")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 2)  # first_visit, is_first_movie
        self.assertEqual(response.json()["results"][0]["name"], "first_visit")
        self.assertEqual(response.json()["results"][1]["name"], "is_first_movie")

        order_ids_first_str = f'["{str(ids[0])}"]'
        response = self.client.get(
            f'/api/projects/@current/property_definitions/?search=firs&{urllib.parse.urlencode({"order_ids_first": order_ids_first_str})}'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 2)
        self.assertEqual(response.json()["results"][0]["id"], str(ids[0]))  # Test that included id is first item
        self.assertEqual(response.json()["results"][0]["name"], "is_first_movie")

        response = self.client.get(
            f'/api/projects/@current/property_definitions/?search=firs&{urllib.parse.urlencode({"order_ids_first": []})}'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 2)  # first_visit, is_first_movie
        self.assertEqual(response.json()["results"][0]["name"], "first_visit")
        self.assertEqual(response.json()["results"][1]["name"], "is_first_movie")

    def test_excluded_ids_filter(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2010, 1, 19, 3, 14, 7)
        )
        # is_first_movie, first_visit
        is_first_movie_property = EnterprisePropertyDefinition.objects.create(team=self.team, name="is_first_movie")
        first_visit_property = EnterprisePropertyDefinition.objects.create(team=self.team, name="first_visit")
        ids = [is_first_movie_property.id, first_visit_property.id]

        response = self.client.get("/api/projects/@current/property_definitions/?search=firs")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 2)  # first_visit, is_first_movie
        self.assertEqual(response.json()["results"][0]["name"], "first_visit")
        self.assertEqual(response.json()["results"][1]["name"], "is_first_movie")

        excluded_ids_str = f'["{str(ids[0])}"]'
        response = self.client.get(
            f'/api/projects/@current/property_definitions/?search=firs&{urllib.parse.urlencode({"excluded_ids": excluded_ids_str})}'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["id"], str(ids[1]))
        self.assertEqual(response.json()["results"][0]["name"], "first_visit")

        response = self.client.get(
            f'/api/projects/@current/property_definitions/?search=firs&{urllib.parse.urlencode({"excluded_ids": []})}'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 2)  # first_visit, is_first_movie
        self.assertEqual(response.json()["results"][0]["name"], "first_visit")
        self.assertEqual(response.json()["results"][1]["name"], "is_first_movie")

    def test_order_ids_first_overrides_excluded_ids_filter(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2010, 1, 19, 3, 14, 7)
        )
        # is_first_movie, first_visit
        is_first_movie_property = EnterprisePropertyDefinition.objects.create(team=self.team, name="is_first_movie")
        first_visit_property = EnterprisePropertyDefinition.objects.create(team=self.team, name="first_visit")
        ids = [is_first_movie_property.id, first_visit_property.id]

        response = self.client.get("/api/projects/@current/property_definitions/?search=firs")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 2)  # first_visit, is_first_movie
        self.assertEqual(response.json()["results"][0]["name"], "first_visit")
        self.assertEqual(response.json()["results"][1]["name"], "is_first_movie")

        ids_str = f'["{str(ids[0])}"]'
        response = self.client.get(
            f'/api/projects/@current/property_definitions/?search=firs&{urllib.parse.urlencode({"excluded_ids": ids_str, "order_ids_first": ids_str})}'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 2)
        self.assertEqual(response.json()["results"][0]["id"], str(ids[0]))
        self.assertEqual(response.json()["results"][0]["name"], "is_first_movie")

        response = self.client.get(
            f'/api/projects/@current/property_definitions/?search=firs&{urllib.parse.urlencode({"excluded_ids": [], "order_ids_first": []})}'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 2)  # first_visit, is_first_movie
        self.assertEqual(response.json()["results"][0]["name"], "first_visit")
        self.assertEqual(response.json()["results"][1]["name"], "is_first_movie")
