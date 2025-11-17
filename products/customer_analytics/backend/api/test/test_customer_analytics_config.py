from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models.team.team import Team

from products.customer_analytics.backend.models import CustomerAnalyticsConfig


class TestCustomerAnalyticsConfigAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.base_url = f"/api/projects/{self.team.id}/customer_analytics_config"

    def test_get_or_create_on_list(self):
        response = self.client.get(self.base_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIsInstance(data, dict)
        self.assertIsNotNone(data["id"])
        self.assertEqual(data["activity_event"], {})

        first_id = data["id"]

        response = self.client.get(self.base_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["id"], first_id)
        self.assertEqual(CustomerAnalyticsConfig.objects.filter(team=self.team).count(), 1)

    def test_create_updates_existing_config(self):
        initial_data = {
            "activity_event": {
                "event_name": "initial_event",
                "properties": ["prop1"],
            }
        }

        response = self.client.post(
            self.base_url,
            data=initial_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        first_id = response.json()["id"]
        updated_data = {
            "activity_event": {
                "event_name": "updated_event",
                "properties": ["prop2", "prop3"],
            }
        }

        response = self.client.post(
            self.base_url,
            data=updated_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, "Should return 200, as it is an update")
        self.assertEqual(response.json()["id"], first_id)
        self.assertEqual(response.json()["activity_event"], updated_data["activity_event"])
        self.assertEqual(
            CustomerAnalyticsConfig.objects.filter(team=self.team).count(), 1, "There should only be one config"
        )

    def test_list_configs_returns_single_object(self):
        config = CustomerAnalyticsConfig.objects.create(
            team=self.team,
            activity_event={"event_name": "test_event"},
        )

        response = self.client.get(self.base_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIsInstance(data, dict, "Should return single object, not array")
        self.assertEqual(data["id"], str(config.id))

    def test_retrieve_config(self):
        config = CustomerAnalyticsConfig.objects.create(
            team=self.team,
            activity_event={"event_name": "test_event"},
        )

        response = self.client.get(f"{self.base_url}/{config.id}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["id"], str(config.id))
        self.assertEqual(response.json()["activity_event"], config.activity_event)

    def test_update_config(self):
        config = CustomerAnalyticsConfig.objects.create(
            team=self.team,
            activity_event={"event_name": "old_event"},
        )
        data = {
            "activity_event": {
                "event_name": "new_event",
                "properties": ["prop1", "prop2"],
            }
        }

        response = self.client.patch(
            f"{self.base_url}/{config.id}",
            data=data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["activity_event"], data["activity_event"])

    def test_delete_config(self):
        config = CustomerAnalyticsConfig.objects.create(
            team=self.team,
            activity_event={"event_name": "test_event"},
        )

        response = self.client.delete(f"{self.base_url}/{config.id}")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(CustomerAnalyticsConfig.objects.filter(id=config.id).exists())

    def test_team_isolation(self):
        team2 = Team.objects.create(organization=self.organization, name="Team 2")
        config1 = CustomerAnalyticsConfig.objects.create(
            team=self.team,
            activity_event={"event_name": "team1_event"},
        )
        config2 = CustomerAnalyticsConfig.objects.create(
            team=team2,
            activity_event={"event_name": "team2_event"},
        )

        response = self.client.get(self.base_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["id"], str(config1.id))
        self.assertNotEqual(response.json()["id"], str(config2.id))

        response = self.client.get(f"{self.base_url}/{config2.id}")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND, "Can't access other team's config")

    def test_one_to_one_constraint(self):
        CustomerAnalyticsConfig.objects.create(
            team=self.team,
            activity_event={"event_name": "first"},
        )

        self.assertEqual(CustomerAnalyticsConfig.objects.filter(team=self.team).count(), 1)

        from django.db import IntegrityError

        with self.assertRaises(IntegrityError):
            CustomerAnalyticsConfig.objects.create(team=self.team, activity_event={"event_name": "second"})

    def test_unauthorized_access(self):
        self.client.logout()

        response = self.client.get(self.base_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_empty_activity_event(self):
        response = self.client.post(
            self.base_url,
            data={},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["activity_event"], {})

    def test_complex_activity_event_structure(self):
        complex_data = {
            "activity_event": {
                "event_name": "user_interaction",
                "properties": {
                    "required": ["user_id", "session_id"],
                    "optional": ["referrer", "utm_source"],
                },
                "filters": {
                    "exclude": ["bot_traffic"],
                    "include_only": {"user_type": ["paid", "trial"]},
                },
                "aggregations": [
                    {"type": "count", "field": "event_id"},
                    {"type": "sum", "field": "revenue"},
                ],
            }
        }
        response = self.client.post(
            self.base_url,
            data=complex_data,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["activity_event"], complex_data["activity_event"])
