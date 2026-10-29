import json

from posthog.test.base import APIBaseTest

from django.test import override_settings

from rest_framework import status

from posthog.schema import PersonsOnEventsMode

from posthog.clickhouse.client import sync_execute
from posthog.models import Organization, PersonalAPIKey, Team, User
from posthog.models.instance_setting import override_instance_config


class TestPlaywrightSetup(APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = False  # Each test gets fresh data to prevent isolation issues

    def test_endpoint_blocked_in_production(self):
        """Test that the endpoint is blocked when not in test/debug/CI modes"""
        with override_settings(TEST=False, DEBUG=False, CI=False, E2E_TESTING=False):
            response = self.client.post("/api/setup_test/organization_with_team/", {})
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @override_settings(TEST=True)
    def test_organization_with_team_setup(self):
        """Test the organization_with_team setup function"""
        payload = {"organization_name": "Test Org API"}

        response = self.client.post("/api/setup_test/organization_with_team/", payload, format="json")

        # Check response structure
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertTrue(data["success"])
        self.assertEqual(data["test_name"], "organization_with_team")
        self.assertIn("result", data)

        result = data["result"]

        # Check all required fields are present
        required_fields = [
            "organization_id",
            "team_id",
            "user_id",
            "organization_name",
            "team_name",
            "user_email",
            "personal_api_key",
        ]
        for field in required_fields:
            self.assertIn(field, result)
            self.assertIsNotNone(result[field])

        # Verify the actual data matches what we requested
        self.assertEqual(result["organization_name"], "Test Org API")

        # Verify database objects were created
        org = Organization.objects.get(id=result["organization_id"])
        self.assertEqual(org.name, "Test Org API")

        team = Team.objects.get(id=result["team_id"])
        self.assertEqual(team.organization, org)

        user = User.objects.get(id=result["user_id"])

        # Verify API key was created and is valid
        api_key = PersonalAPIKey.objects.get(user=user)
        self.assertEqual(api_key.label, "Test API Key")
        self.assertIn("*", api_key.scopes)  # Should have full access
        self.assertTrue(result["personal_api_key"].startswith("phx_"))

    @override_settings(TEST=True)
    def test_organization_with_team_pins_the_production_person_on_events_mode(self):
        # The instance setting is off on purpose, so the assertion proves the team's own modifiers
        # rather than the ambient setting. Playwright CI runs with it unset and DEBUG off.
        with override_instance_config("PERSON_ON_EVENTS_V2_ENABLED", False):
            response = self.client.post(
                "/api/setup_test/organization_with_team/", {"no_demo_data": True}, format="json"
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            team = Team.objects.get(id=response.json()["result"]["team_id"])
            self.assertEqual(team.person_on_events_mode, PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS)
            self.assertTrue(team.person_on_events_querying_enabled)

    @override_settings(TEST=True)
    def test_seeded_events_carry_person_properties_as_of_each_event(self):
        # A person-on-events mode reads person properties off the event, not the person table.
        payload = {
            "no_demo_data": True,
            "persons": [{"distinct_ids": ["seeded-person"], "properties": {"plan": "free"}}],
            "events": [
                {
                    "event": "$pageview",
                    "distinct_id": "seeded-person",
                    "timestamp": "2024-11-03T10:00:00Z",
                },
                {
                    "event": "$pageview",
                    "distinct_id": "seeded-person",
                    "timestamp": "2024-11-03T12:00:00Z",
                    "properties": {"$set": {"plan": "paid"}},
                },
            ],
        }
        response = self.client.post("/api/setup_test/organization_with_team/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        team_id = int(response.json()["result"]["team_id"])
        rows = sync_execute(
            "SELECT person_properties FROM events WHERE team_id = %(team_id)s ORDER BY timestamp",
            {"team_id": team_id},
        )
        self.assertEqual(
            [json.loads(row[0]) for row in rows],
            [{"plan": "free"}, {"plan": "paid"}],
        )

    @override_settings(DEBUG=True)
    def test_endpoint_allowed_in_debug_mode(self):
        """Test that the endpoint works in DEBUG mode"""
        payload = {"organization_name": "Debug Org"}
        response = self.client.post("/api/setup_test/organization_with_team/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_endpoint_allowed_in_e2e_mode(self):
        """Test that the endpoint works in E2E_TESTING mode"""
        self.ensure_url_patterns_loaded()

        with override_settings(E2E_TESTING=True):
            payload = {"organization_name": "E2E Org", "no_demo_data": True}
            response = self.client.post("/api/setup_test/organization_with_team/", payload, format="json")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

    @override_settings(TEST=True)
    def test_unknown_setup_function(self):
        """Test handling of unknown setup function"""
        response = self.client.post("/api/setup_test/nonexistent_setup/", {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        data = response.json()
        self.assertIn("not found", data["error"])
        self.assertIn("available_tests", data)
        self.assertIn("organization_with_team", data["available_tests"])

    @override_settings(TEST=True)
    def test_setup_with_defaults(self):
        """Test setup function with default parameters (empty payload)"""
        response = self.client.post("/api/setup_test/organization_with_team/", {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        result = data["result"]

        # Should use default values
        self.assertEqual(result["organization_name"], "Hedgebox Inc.")
