from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status
from slack_sdk.errors import SlackApiError

from posthog.cdp.templates.hog_function_template import sync_template_to_db
from posthog.cdp.templates.slack.template_slack import template as template_slack
from posthog.models import Integration, Organization, Team

from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.customer_analytics.backend.logic.event_stream_destination import _NO_MEMBERS_SENTINEL
from products.customer_analytics.backend.models import EventStream, EventStreamMember, TeamCustomerAnalyticsConfig
from products.customer_analytics.backend.test.factories import create_account


class TestEventStreamViewSet(APIBaseTest):
    def setUp(self):
        super().setUp()
        sync_template_to_db(template_slack)
        TeamCustomerAnalyticsConfig.objects.update_or_create(team=self.team, defaults={"account_group_type_index": 0})
        self.integration = Integration.objects.create(
            team=self.team, kind="slack", config={"team": {"id": "T123"}}, sensitive_config={"access_token": "x"}
        )
        self.base_url = f"/api/projects/{self.team.id}/event_streams/"
        self.valid_data = {
            "enabled": True,
            "event_names": ["$pageview", "dashboard_created"],
            "slack_integration": self.integration.id,
            "slack_channel_id": "C0123ABC",
            "slack_channel_name": "#customer-events",
        }

    def _create_stream(self, data: dict | None = None) -> dict:
        response = self.client.post(self.base_url, data or self.valid_data, format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        return response.json()

    def _destination(self, stream: dict) -> HogFunction:
        hog_function_id = EventStream.objects.unscoped().get(id=stream["id"]).hog_function_id
        assert hog_function_id is not None
        return HogFunction.objects.get(id=hog_function_id)

    def _group_filter(self, function: HogFunction) -> dict:
        return (function.filters or {})["properties"][0]

    def _inputs(self, function: HogFunction) -> dict:
        return function.inputs or {}

    def _filtered_events(self, function: HogFunction) -> list[dict]:
        return (function.filters or {})["events"]

    def test_create_without_slack_defers_destination_until_channel_is_set(self):
        stream = self._create_stream({"event_names": ["$pageview"]})

        self.assertIsNone(EventStream.objects.unscoped().get(id=stream["id"]).hog_function_id)

        response = self.client.patch(
            f"{self.base_url}{stream['id']}/",
            {"slack_integration": self.integration.id, "slack_channel_id": "C0123ABC"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        function = self._destination(stream)
        self.assertEqual(self._inputs(function)["slack_workspace"]["value"], self.integration.id)
        self.assertEqual(self._inputs(function)["channel"]["value"], "C0123ABC")

    def test_clearing_channel_keeps_existing_destination_inputs(self):
        stream = self._create_stream()

        response = self.client.patch(f"{self.base_url}{stream['id']}/", {"slack_channel_id": ""}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        function = self._destination(stream)
        self.assertFalse(function.enabled)
        self.assertEqual(self._inputs(function)["slack_workspace"]["value"], self.integration.id)
        self.assertEqual(self._inputs(function)["channel"]["value"], "C0123ABC")

    def test_create_provisions_disabled_destination_until_members_exist(self):
        stream = self._create_stream()

        function = self._destination(stream)
        self.assertEqual(function.template_id, "template-slack")
        self.assertEqual(function.type, "destination")
        self.assertFalse(function.enabled)
        self.assertEqual(self._group_filter(function)["value"], [_NO_MEMBERS_SENTINEL])
        self.assertEqual(self._inputs(function)["slack_workspace"]["value"], self.integration.id)
        self.assertEqual(self._inputs(function)["channel"]["value"], "C0123ABC")

    def test_add_and_remove_account_resyncs_destination_filters(self):
        stream = self._create_stream()
        acme = create_account(team_id=self.team.id, name="Acme", external_id="org-acme")
        globex = create_account(team_id=self.team.id, name="Globex", external_id="org-globex")

        for account in (acme, globex):
            response = self.client.post(
                f"{self.base_url}{stream['id']}/add_account/", {"account_id": str(account.id)}, format="json"
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())

        self.assertCountEqual(response.json()["account_ids"], [str(acme.id), str(globex.id)])
        function = self._destination(stream)
        self.assertTrue(function.enabled)
        self.assertEqual(
            self._group_filter(function),
            {"key": "$group_0", "value": ["org-acme", "org-globex"], "operator": "exact", "type": "event"},
        )
        self.assertEqual([event["id"] for event in self._filtered_events(function)], ["$pageview", "dashboard_created"])

        for account in (acme, globex):
            response = self.client.post(
                f"{self.base_url}{stream['id']}/remove_account/", {"account_id": str(account.id)}, format="json"
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())

        self.assertEqual(response.json()["account_ids"], [])
        function.refresh_from_db()
        self.assertFalse(function.enabled)
        self.assertEqual(self._group_filter(function)["value"], [_NO_MEMBERS_SENTINEL])

    def test_account_without_external_id_does_not_enable_destination(self):
        stream = self._create_stream()
        account = create_account(team_id=self.team.id, name="No group key", external_id=None)

        response = self.client.post(
            f"{self.base_url}{stream['id']}/add_account/", {"account_id": str(account.id)}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        self.assertEqual(response.json()["account_ids"], [str(account.id)])
        function = self._destination(stream)
        self.assertFalse(function.enabled)
        self.assertEqual(self._group_filter(function)["value"], [_NO_MEMBERS_SENTINEL])

    def test_second_stream_for_same_user_conflicts(self):
        self._create_stream()

        response = self.client.post(self.base_url, self.valid_data, format="json")

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(EventStream.objects.unscoped().filter(team_id=self.team.id).count(), 1)

    def test_deleting_owner_deletes_stream_and_archives_destination(self):
        stream = self._create_stream()
        function = self._destination(stream)

        self.user.delete()

        self.assertFalse(EventStream.objects.unscoped().filter(id=stream["id"]).exists())
        function.refresh_from_db()
        self.assertTrue(function.deleted)
        self.assertFalse(function.enabled)

    def test_streams_are_per_user(self):
        stream = self._create_stream()
        teammate = self._create_user("teammate@posthog.com")
        self.client.force_login(teammate)

        self.assertEqual(self.client.get(self.base_url).json(), [])
        response = self.client.patch(f"{self.base_url}{stream['id']}/", {"enabled": False}, format="json")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        response = self.client.post(self.base_url, self.valid_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        self.assertEqual(EventStream.objects.unscoped().filter(team_id=self.team.id).count(), 2)

    def test_foreign_slack_integration_is_rejected(self):
        other_org = Organization.objects.create(name="other org")
        other_team = Team.objects.create(organization=other_org, name="other team")
        foreign_integration = Integration.objects.create(team=other_team, kind="slack", config={}, sensitive_config={})

        response = self.client.post(
            self.base_url, {**self.valid_data, "slack_integration": foreign_integration.id}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(EventStream.objects.unscoped().filter(team_id=self.team.id).exists())

    def test_foreign_account_is_rejected_on_add(self):
        stream = self._create_stream()
        other_org = Organization.objects.create(name="other org")
        other_team = Team.objects.create(organization=other_org, name="other team")
        foreign_account = create_account(team_id=other_team.id, name="Foreign", external_id="org-foreign")

        response = self.client.post(
            f"{self.base_url}{stream['id']}/add_account/", {"account_id": str(foreign_account.id)}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(EventStreamMember.objects.unscoped().filter(stream_id=stream["id"]).exists())
        self.assertEqual(self._group_filter(self._destination(stream))["value"], [_NO_MEMBERS_SENTINEL])

    def test_update_resyncs_destination_and_normalizes_event_names(self):
        stream = self._create_stream()
        account = create_account(team_id=self.team.id, name="Acme", external_id="org-acme")
        self.client.post(f"{self.base_url}{stream['id']}/add_account/", {"account_id": str(account.id)}, format="json")

        response = self.client.patch(
            f"{self.base_url}{stream['id']}/",
            {"event_names": ["signup", "signup", "invoice_paid"]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        self.assertEqual(response.json()["event_names"], ["signup", "invoice_paid"])
        function = self._destination(stream)
        self.assertEqual([event["id"] for event in self._filtered_events(function)], ["signup", "invoice_paid"])
        self.assertTrue(function.enabled)

        response = self.client.patch(f"{self.base_url}{stream['id']}/", {"enabled": False}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        function.refresh_from_db()
        self.assertFalse(function.enabled)

    def test_destroy_archives_destination(self):
        stream = self._create_stream()
        function = self._destination(stream)

        response = self.client.delete(f"{self.base_url}{stream['id']}/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(EventStream.objects.unscoped().filter(id=stream["id"]).exists())
        function.refresh_from_db()
        self.assertTrue(function.deleted)
        self.assertFalse(function.enabled)

    @patch("products.customer_analytics.backend.logic.event_stream_destination.SlackIntegration")
    def test_send_test_message_posts_to_configured_channel(self, mock_slack):
        stream = self._create_stream()

        response = self.client.post(f"{self.base_url}{stream['id']}/send_test_message/")

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        self.assertEqual(response.json(), {"channel_id": "C0123ABC"})
        self.assertEqual(mock_slack.return_value.client.chat_postMessage.call_args.kwargs["channel"], "C0123ABC")

    @patch("products.customer_analytics.backend.logic.event_stream_destination.SlackIntegration")
    def test_send_test_message_requires_saved_slack_config(self, mock_slack):
        stream = self._create_stream({"event_names": ["$pageview"]})

        response = self.client.post(f"{self.base_url}{stream['id']}/send_test_message/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        mock_slack.return_value.client.chat_postMessage.assert_not_called()

    @patch("products.customer_analytics.backend.logic.event_stream_destination.SlackIntegration")
    def test_send_test_message_surfaces_slack_rejection(self, mock_slack):
        mock_slack.return_value.client.chat_postMessage.side_effect = SlackApiError(
            "error", {"error": "not_in_channel"}
        )
        stream = self._create_stream()

        response = self.client.post(f"{self.base_url}{stream['id']}/send_test_message/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("not_in_channel", response.json()["detail"])

    def test_list_is_team_scoped(self):
        stream = self._create_stream()
        other_org = Organization.objects.create(name="other org")
        other_team = Team.objects.create(organization=other_org, name="other team")
        EventStream.objects.unscoped().create(team=other_team, event_names=["foreign_event"])

        response = self.client.get(self.base_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([row["id"] for row in response.json()], [stream["id"]])
