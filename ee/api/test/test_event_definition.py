import urllib.parse
from typing import cast

import dateutil.parser
from django.utils import timezone
from freezegun import freeze_time
from rest_framework import status

from ee.models.event_definition import EnterpriseEventDefinition
from ee.models.license import License, LicenseManager
from posthog.models import Tag
from posthog.models.event_definition import EventDefinition
from posthog.test.base import APIBaseTest


class TestEventDefinitionEnterpriseAPI(APIBaseTest):
    def test_retrieve_existing_event_definition(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2500, 1, 19, 3, 14, 7)
        )
        event = EnterpriseEventDefinition.objects.create(team=self.team, name="enterprise event", owner=self.user)
        tag = Tag.objects.create(name="deprecated", team_id=self.team.id)
        event.tagged_items.create(tag_id=tag.id)
        response = self.client.get(f"/api/projects/@current/event_definitions/{event.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(response_data["name"], "enterprise event")
        self.assertEqual(response_data["description"], "")
        self.assertEqual(response_data["tags"], ["deprecated"])
        self.assertEqual(response_data["owner"]["id"], self.user.id)

        self.assertAlmostEqual(
            (timezone.now() - dateutil.parser.isoparse(response_data["created_at"])).total_seconds(), 0, delta=1
        )
        self.assertIn("last_seen_at", response_data)

    def test_retrieve_create_event_definition(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2500, 1, 19, 3, 14, 7)
        )
        event = EventDefinition.objects.create(team=self.team, name="event")
        response = self.client.get(f"/api/projects/@current/event_definitions/{event.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        enterprise_event = EnterpriseEventDefinition.objects.all().first()
        event.refresh_from_db()
        self.assertEqual(enterprise_event.eventdefinition_ptr_id, event.id)  # type: ignore
        self.assertEqual(enterprise_event.name, event.name)  # type: ignore
        self.assertEqual(enterprise_event.team.id, event.team.id)  # type: ignore

    def test_search_event_definition(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2500, 1, 19, 3, 14, 7)
        )
        enterprise_property = EnterpriseEventDefinition.objects.create(
            team=self.team, name="enterprise event", owner=self.user
        )
        tag = Tag.objects.create(name="deprecated", team_id=self.team.id)
        enterprise_property.tagged_items.create(tag_id=tag.id)
        regular_event = EnterpriseEventDefinition.objects.create(team=self.team, name="regular event", owner=self.user)
        regular_event.tagged_items.create(tag_id=tag.id)

        response = self.client.get(f"/api/projects/@current/event_definitions/?search=enter")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(len(response_data["results"]), 1)

        self.assertEqual(response_data["results"][0]["name"], "enterprise event")
        self.assertEqual(response_data["results"][0]["description"], "")
        self.assertEqual(response_data["results"][0]["tags"], ["deprecated"])
        self.assertEqual(response_data["results"][0]["owner"]["id"], self.user.id)

        response = self.client.get(f"/api/projects/@current/event_definitions/?search=enterprise")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(len(response_data["results"]), 1)

        response = self.client.get(f"/api/projects/@current/event_definitions/?search=e ev")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(len(response_data["results"]), 2)

        response = self.client.get(f"/api/projects/@current/event_definitions/?search=bust")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(len(response_data["results"]), 0)

    def test_update_event_definition(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2038, 1, 19, 3, 14, 7)
        )
        event = EnterpriseEventDefinition.objects.create(team=self.team, name="enterprise event", owner=self.user)
        response = self.client.patch(
            f"/api/projects/@current/event_definitions/{str(event.id)}/",
            {"description": "This is a description.", "tags": ["official", "internal"],},
        )
        response_data = response.json()
        self.assertEqual(response_data["description"], "This is a description.")
        self.assertEqual(response_data["updated_by"]["first_name"], self.user.first_name)
        self.assertEqual(set(response_data["tags"]), {"official", "internal"})

        event.refresh_from_db()
        self.assertEqual(event.description, "This is a description.")
        self.assertEqual(set(event.tagged_items.values_list("tag__name", flat=True)), {"official", "internal"})

    def test_update_event_without_license(self):
        event = EnterpriseEventDefinition.objects.create(team=self.team, name="enterprise event")
        response = self.client.patch(
            f"/api/projects/@current/event_definitions/{str(event.id)}", data={"description": "test"},
        )
        self.assertEqual(response.status_code, status.HTTP_402_PAYMENT_REQUIRED)
        self.assertIn("This feature is part of the premium PostHog offering.", response.json()["detail"])

    def test_with_expired_license(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2010, 1, 19, 3, 14, 7)
        )
        event = EnterpriseEventDefinition.objects.create(team=self.team, name="description test")
        response = self.client.patch(
            f"/api/projects/@current/event_definitions/{str(event.id)}", data={"description": "test"},
        )
        self.assertEqual(response.status_code, status.HTTP_402_PAYMENT_REQUIRED)
        self.assertIn("This feature is part of the premium PostHog offering.", response.json()["detail"])

    @freeze_time("2021-08-25T22:09:14.252Z")
    def test_can_get_event_verification_data(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2500, 1, 19, 3, 14, 7)
        )
        event = EnterpriseEventDefinition.objects.create(team=self.team, name="enterprise event", owner=self.user)
        response = self.client.get(f"/api/projects/@current/event_definitions/{event.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        assert response.json()["verified"] is False
        assert response.json()["verified_by"] is None
        assert response.json()["verified_at"] is None
        assert response.json()["updated_at"] == "2021-08-25T22:09:14.252000Z"

        query_list_response = self.client.get(f"/api/projects/@current/event_definitions")
        matches = [p["name"] for p in query_list_response.json()["results"] if p["name"] == "enterprise event"]
        assert len(matches) == 1

    @freeze_time("2021-08-25T22:09:14.252Z")
    def test_verify_then_unverify(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2500, 1, 19, 3, 14, 7)
        )
        event = EnterpriseEventDefinition.objects.create(team=self.team, name="enterprise event", owner=self.user)
        response = self.client.get(f"/api/projects/@current/event_definitions/{event.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        assert response.json()["verified"] is False
        assert response.json()["verified_by"] is None
        assert response.json()["verified_at"] is None

        # Verify the event
        self.client.patch(f"/api/projects/@current/event_definitions/{event.id}", {"verified": True})
        response = self.client.get(f"/api/projects/@current/event_definitions/{event.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        assert response.json()["verified"] is True
        assert response.json()["verified_by"]["id"] == self.user.id
        assert response.json()["verified_at"] == "2021-08-25T22:09:14.252000Z"

        # Unverify the event
        self.client.patch(f"/api/projects/@current/event_definitions/{event.id}", {"verified": False})
        response = self.client.get(f"/api/projects/@current/event_definitions/{event.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        assert response.json()["verified"] is False
        assert response.json()["verified_by"] is None
        assert response.json()["verified_at"] is None

    def test_verify_then_verify_again_no_change(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2500, 1, 19, 3, 14, 7)
        )
        event = EnterpriseEventDefinition.objects.create(team=self.team, name="enterprise event", owner=self.user)
        response = self.client.get(f"/api/projects/@current/event_definitions/{event.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        assert response.json()["verified"] is False
        assert response.json()["verified_by"] is None
        assert response.json()["verified_at"] is None

        with freeze_time("2021-08-25T22:09:14.252Z"):
            self.client.patch(f"/api/projects/@current/event_definitions/{event.id}", {"verified": True})
            response = self.client.get(f"/api/projects/@current/event_definitions/{event.id}")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        assert response.json()["verified"] is True
        assert response.json()["verified_by"]["id"] == self.user.id
        assert response.json()["verified_at"] == "2021-08-25T22:09:14.252000Z"
        assert response.json()["updated_at"] == "2021-08-25T22:09:14.252000Z"

        with freeze_time("2021-10-26T22:09:14.252Z"):
            self.client.patch(f"/api/projects/@current/event_definitions/{event.id}", {"verified": True})
            response = self.client.get(f"/api/projects/@current/event_definitions/{event.id}")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        assert response.json()["verified"] is True
        assert response.json()["verified_by"]["id"] == self.user.id
        assert response.json()["verified_at"] == "2021-08-25T22:09:14.252000Z"  # Note `verified_at` did not change
        # updated_at automatically updates on every patch request
        assert response.json()["updated_at"] == "2021-10-26T22:09:14.252000Z"

    @freeze_time("2021-08-25T22:09:14.252Z")
    def test_cannot_update_verified_meta_properties_directly(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2500, 1, 19, 3, 14, 7)
        )
        event = EnterpriseEventDefinition.objects.create(team=self.team, name="enterprise event", owner=self.user)
        response = self.client.get(f"/api/projects/@current/event_definitions/{event.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        assert response.json()["verified"] is False
        assert response.json()["verified_by"] is None
        assert response.json()["verified_at"] is None

        with freeze_time("2021-08-25T22:09:14.252Z"):
            self.client.patch(
                f"/api/projects/@current/event_definitions/{event.id}",
                {
                    "verified_by": self.user.id,
                    "verified_at": timezone.now(),
                },  # These properties are ignored by the serializer
            )
            response = self.client.get(f"/api/projects/@current/event_definitions/{event.id}")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        assert response.json()["verified"] is False
        assert response.json()["verified_by"] is None
        assert response.json()["verified_at"] is None

    def test_event_definition_no_duplicate_tags(self):
        from ee.models.license import License, LicenseManager

        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            key="key_123", plan="enterprise", valid_until=timezone.datetime(2038, 1, 19, 3, 14, 7), max_users=3,
        )
        event = EnterpriseEventDefinition.objects.create(team=self.team, name="enterprise event")
        response = self.client.patch(
            f"/api/projects/@current/event_definitions/{str(event.id)}", data={"tags": ["a", "b", "a"]},
        )

        self.assertListEqual(sorted(response.json()["tags"]), ["a", "b"])

    def test_order_ids_first_filter(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2500, 1, 19, 3, 14, 7)
        )
        # rated_app, installed_app
        rated_app_event = EnterpriseEventDefinition.objects.create(team=self.team, name="rated_app")
        installed_app_event = EnterpriseEventDefinition.objects.create(team=self.team, name="installed_app")
        ids = [rated_app_event.id, installed_app_event.id]

        response = self.client.get("/api/projects/@current/event_definitions/?search=app")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 2)  # installed_app, rated_app
        self.assertEqual(response.json()["results"][0]["name"], "installed_app")
        self.assertEqual(response.json()["results"][1]["name"], "rated_app")

        order_ids_first_str = f'["{str(ids[0])}"]'
        response = self.client.get(
            f'/api/projects/@current/event_definitions/?search=app&{urllib.parse.urlencode({"order_ids_first": order_ids_first_str})}'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 2)
        self.assertEqual(response.json()["results"][0]["id"], str(ids[0]))  # Test that included id is first item
        self.assertEqual(response.json()["results"][0]["name"], "rated_app")

        response = self.client.get(
            f'/api/projects/@current/event_definitions/?search=app&{urllib.parse.urlencode({"order_ids_first": []})}'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 2)  # installed_app, rated_app
        self.assertEqual(response.json()["results"][0]["name"], "installed_app")
        self.assertEqual(response.json()["results"][1]["name"], "rated_app")

    def test_excluded_ids_filter(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2500, 1, 19, 3, 14, 7)
        )
        # rated_app, installed_app
        rated_app_event = EnterpriseEventDefinition.objects.create(team=self.team, name="rated_app")
        installed_app_event = EnterpriseEventDefinition.objects.create(team=self.team, name="installed_app")
        ids = [rated_app_event.id, installed_app_event.id]

        response = self.client.get("/api/projects/@current/event_definitions/?search=app")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 2)  # installed_app, rated_app
        self.assertEqual(response.json()["results"][0]["name"], "installed_app")
        self.assertEqual(response.json()["results"][1]["name"], "rated_app")

        excluded_ids_str = f'["{str(ids[0])}"]'
        response = self.client.get(
            f'/api/projects/@current/event_definitions/?search=app&{urllib.parse.urlencode({"excluded_ids": excluded_ids_str})}'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["id"], str(ids[1]))
        self.assertEqual(response.json()["results"][0]["name"], "installed_app")

        response = self.client.get(
            f'/api/projects/@current/event_definitions/?search=app&{urllib.parse.urlencode({"excluded_ids": []})}'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 2)  # installed_app, rated_app
        self.assertEqual(response.json()["results"][0]["name"], "installed_app")
        self.assertEqual(response.json()["results"][1]["name"], "rated_app")

    def test_order_ids_first_overrides_excluded_ids_filter(self):
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            plan="enterprise", valid_until=timezone.datetime(2500, 1, 19, 3, 14, 7)
        )
        # rated_app, installed_app
        rated_app_event = EnterpriseEventDefinition.objects.create(team=self.team, name="rated_app")
        installed_app_event = EnterpriseEventDefinition.objects.create(team=self.team, name="installed_app")
        ids = [rated_app_event.id, installed_app_event.id]

        response = self.client.get("/api/projects/@current/event_definitions/?search=app")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 2)  # installed_app, rated_app
        self.assertEqual(response.json()["results"][0]["name"], "installed_app")
        self.assertEqual(response.json()["results"][1]["name"], "rated_app")

        ids_str = f'["{str(ids[0])}"]'
        response = self.client.get(
            f'/api/projects/@current/event_definitions/?search=app&{urllib.parse.urlencode({"excluded_ids": ids_str, "order_ids_first": ids_str})}'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 2)
        self.assertEqual(response.json()["results"][0]["id"], str(ids[0]))
        self.assertEqual(response.json()["results"][0]["name"], "rated_app")

        response = self.client.get(
            f'/api/projects/@current/event_definitions/?search=app&{urllib.parse.urlencode({"excluded_ids": [], "order_ids_first": []})}'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 2)  # installed_app, rated_app
        self.assertEqual(response.json()["results"][0]["name"], "installed_app")
        self.assertEqual(response.json()["results"][1]["name"], "rated_app")
