from uuid import uuid4

import pytest
from freezegun import freeze_time
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.apps import apps

from parameterized import parameterized
from rest_framework import status

from posthog.api.tagged_item import set_tags_on_object
from posthog.constants import AvailableFeature
from posthog.models import Tag, TaggedItem
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team
from posthog.models.user import User

from products.customer_analytics.backend.logic import relationships as relationships_logic
from products.customer_analytics.backend.models import (
    Account,
    AccountRelationship,
    AccountRelationshipDefinition,
    CustomerJourney,
    CustomerProfileConfig,
    CustomPropertyDefinition,
    CustomPropertySource,
    DisplayType,
)
from products.customer_analytics.backend.models.account import AccountAssignment
from products.customer_analytics.backend.test.factories import create_account, create_custom_property_definition
from products.notebooks.backend.models import Notebook, ResourceNotebook
from products.product_analytics.backend.models.insight import Insight

from ee.models.rbac.access_control import AccessControl


class TestCustomerProfileConfigViewSet(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.endpoint_base = f"/api/environments/{self.team.id}/customer_profile_configs/"
        self.valid_data = {
            "scope": "person",
            "content": [{"type": "ph-node-foo", "index": 0}],
            "sidebar": [{"type": "ph-node-bar"}],
        }

    def assertActivityLog(self, config_id, activity):
        logs = ActivityLog.objects.filter(team_id=self.team.id, scope="CustomerProfileConfig", activity=activity)
        self.assertEqual(logs.count(), 1)
        log = logs.latest("created_at")
        self.assertEqual(log.item_id, str(config_id))

    def test_create_customer_profile_config_success(self):
        response = self.client.post(self.endpoint_base, self.valid_data, format="json")

        self.assertEqual(status.HTTP_201_CREATED, response.status_code, response.json())
        response_data = response.json()

        self.assertIn("id", response_data)
        self.assertEqual("person", response_data["scope"])
        self.assertEqual(self.valid_data["content"], response_data["content"])
        self.assertEqual(self.valid_data["sidebar"], response_data["sidebar"])
        self.assertIn("created_at", response_data)
        self.assertIn("updated_at", response_data)

        # nosemgrep: idor-lookup-without-team (test assertion)
        config = CustomerProfileConfig.objects.get(id=response_data["id"])
        self.assertEqual(config.scope, "person", "Should persist data")
        self.assertEqual(config.team, self.team)
        self.assertEqual(config.content, self.valid_data["content"])
        self.assertEqual(config.sidebar, self.valid_data["sidebar"])
        self.assertEqual(config.created_by, self.user)
        self.assertActivityLog(config.id, "created")

    def test_list_customer_profile_configs(self):
        config1 = CustomerProfileConfig.objects.create(team=self.team, scope="person", content={"type": "person"})
        config2 = CustomerProfileConfig.objects.create(team=self.team, scope="group_0", content={"type": "group"})
        other_team = Team.objects.create(organization=self.organization)
        CustomerProfileConfig.objects.create(team=other_team, scope="person", content={"type": "other"})

        response = self.client.get(self.endpoint_base)

        self.assertEqual(status.HTTP_200_OK, response.status_code)
        response_data = response.json()
        self.assertEqual(response_data["count"], 2, "Should only return configs for current team")
        config_ids = [config["id"] for config in response_data["results"]]
        self.assertIn(str(config1.id), config_ids)
        self.assertIn(str(config2.id), config_ids)

    def test_retrieve_customer_profile_config(self):
        config = CustomerProfileConfig.objects.create(
            team=self.team, scope="person", content=self.valid_data["content"], sidebar=self.valid_data["sidebar"]
        )

        response = self.client.get(f"{self.endpoint_base}{config.id}/")

        self.assertEqual(status.HTTP_200_OK, response.status_code)
        response_data = response.json()
        self.assertEqual(str(config.id), response_data["id"])
        self.assertEqual("person", response_data["scope"])
        self.assertEqual(self.valid_data["content"], response_data["content"])
        self.assertEqual(self.valid_data["sidebar"], response_data["sidebar"])

    def test_update_customer_profile_config(self):
        config = CustomerProfileConfig.objects.create(team=self.team, scope="person", content={"old": "data"})
        update_data = {"scope": "group_0", "content": {"new": "data"}, "sidebar": {"updated": "sidebar"}}

        response = self.client.patch(f"{self.endpoint_base}{config.id}/", update_data, format="json")

        self.assertEqual(status.HTTP_200_OK, response.status_code)
        response_data = response.json()

        self.assertEqual("group_0", response_data["scope"])
        self.assertEqual(update_data["content"], response_data["content"])
        self.assertEqual(update_data["sidebar"], response_data["sidebar"])

        config.refresh_from_db()
        self.assertEqual("group_0", config.scope)
        self.assertEqual(update_data["content"], config.content, "Should update database")
        self.assertActivityLog(config.id, "updated")

    def test_delete_customer_profile_config(self):
        config = CustomerProfileConfig.objects.create(team=self.team, scope="person", content={"test": "data"})
        config_id = str(config.id)

        response = self.client.delete(f"{self.endpoint_base}{config.id}/")

        self.assertEqual(status.HTTP_204_NO_CONTENT, response.status_code)
        self.assertFalse(CustomerProfileConfig.objects.filter(id=config.id).exists())
        self.assertActivityLog(config_id, "deleted")

    @parameterized.expand(
        [
            (
                "invalid_scope",
                {"scope": "quick"},
                {
                    "attr": "scope",
                    "type": "validation_error",
                    "code": "invalid_choice",
                    "detail": '"quick" is not a valid choice.',
                },
            ),
            (
                "content_not_dict",
                {"scope": "person", "content": "not_a_dict"},
                {
                    "attr": "content",
                    "type": "validation_error",
                    "code": "invalid_input",
                    "detail": "Invalid value for field 'content'",
                },
            ),
            (
                "sidebar_not_dict",
                {"scope": "person", "content": {}, "sidebar": "not_a_dict"},
                {
                    "attr": "sidebar",
                    "type": "validation_error",
                    "code": "invalid_input",
                    "detail": "Invalid value for field 'sidebar'",
                },
            ),
            (
                "missing_scope",
                {},
                {"attr": "scope", "type": "validation_error", "code": "required", "detail": "This field is required."},
            ),
        ]
    )
    def test_validation_errors(self, name, invalid_data, expected_response):
        response = self.client.post(self.endpoint_base, invalid_data, format="json")

        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        response_data = response.json()
        self.assertEqual(response_data, expected_response)

    def test_team_isolation(self):
        other_team = Team.objects.create(organization=self.organization)
        other_config = CustomerProfileConfig.objects.create(team=other_team, scope="person", content={"other": "team"})

        response = self.client.get(f"{self.endpoint_base}{other_config.id}/")
        self.assertEqual(status.HTTP_404_NOT_FOUND, response.status_code)

        response = self.client.patch(f"{self.endpoint_base}{other_config.id}/", {"scope": "group_0"}, format="json")
        self.assertEqual(status.HTTP_404_NOT_FOUND, response.status_code)

        response = self.client.delete(f"{self.endpoint_base}{other_config.id}/")
        self.assertEqual(status.HTTP_404_NOT_FOUND, response.status_code)

    def test_scope_choices_validation(self):
        valid_scopes = ["person", "group_0", "group_1", "group_2", "group_3", "group_4"]

        for scope in valid_scopes:
            data = {"scope": scope, "content": {}}
            response = self.client.post(self.endpoint_base, data, format="json")
            self.assertEqual(status.HTTP_201_CREATED, response.status_code, f"Failed for scope: {scope}")

    def test_json_fields_defaults(self):
        data = {"scope": "person", "content": None, "sidebar": None}

        response = self.client.post(self.endpoint_base, data, format="json")

        self.assertEqual(status.HTTP_201_CREATED, response.status_code)
        response_data = response.json()
        self.assertEqual({}, response_data["content"], "Should default to empty dict")
        self.assertEqual({}, response_data["sidebar"], "Should default to empty dict")

    def test_permissions_authentication_required(self):
        self.client.logout()

        endpoints = [
            ("GET", self.endpoint_base),
            ("POST", self.endpoint_base),
            ("GET", f"{self.endpoint_base}test-id/"),
            ("PATCH", f"{self.endpoint_base}test-id/"),
            ("DELETE", f"{self.endpoint_base}test-id/"),
        ]

        for method, url in endpoints:
            response = getattr(self.client, method.lower())(url, format="json")
            self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])


class TestCustomerJourneyViewSet(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.endpoint_base = f"/api/environments/{self.team.id}/customer_journeys/"
        self.insight = Insight.objects.create(team=self.team)

    def _create_journey(self, **kwargs):
        defaults = {"team": self.team, "insight": self.insight, "name": "Test Journey"}
        defaults.update(kwargs)
        return CustomerJourney.objects.create(**defaults)

    def test_create(self):
        response = self.client.post(
            self.endpoint_base,
            {"insight": self.insight.id, "name": "My Journey", "description": "A description"},
            format="json",
        )

        self.assertEqual(status.HTTP_201_CREATED, response.status_code, response.json())
        data = response.json()
        self.assertIn("id", data)
        self.assertEqual(data["name"], "My Journey")
        self.assertEqual(data["description"], "A description")
        self.assertEqual(data["insight"], self.insight.id)
        self.assertIn("created_at", data)
        self.assertIn("updated_at", data)

        journey = CustomerJourney.objects.get(id=data["id"])  # nosemgrep: idor-lookup-without-team
        self.assertEqual(journey.created_by, self.user)
        self.assertEqual(journey.team, self.team)

    def test_list(self):
        insight2 = Insight.objects.create(team=self.team)
        j1 = self._create_journey(name="Journey 1")
        j2 = self._create_journey(name="Journey 2", insight=insight2)

        other_team = Team.objects.create(organization=self.organization)
        other_insight = Insight.objects.create(team=other_team)
        CustomerJourney.objects.create(team=other_team, insight=other_insight, name="Other")

        response = self.client.get(self.endpoint_base)

        self.assertEqual(status.HTTP_200_OK, response.status_code)
        data = response.json()
        self.assertEqual(data["count"], 2)
        ids = {r["id"] for r in data["results"]}
        self.assertEqual(ids, {str(j1.id), str(j2.id)})

    def test_retrieve(self):
        journey = self._create_journey(description="desc")

        response = self.client.get(f"{self.endpoint_base}{journey.id}/")

        self.assertEqual(status.HTTP_200_OK, response.status_code)
        data = response.json()
        self.assertEqual(data["id"], str(journey.id))
        self.assertEqual(data["name"], "Test Journey")
        self.assertEqual(data["description"], "desc")
        self.assertEqual(data["insight"], self.insight.id)

    def test_update(self):
        journey = self._create_journey()

        response = self.client.patch(
            f"{self.endpoint_base}{journey.id}/",
            {"name": "Updated", "description": "New desc"},
            format="json",
        )

        self.assertEqual(status.HTTP_200_OK, response.status_code)
        journey.refresh_from_db()
        self.assertEqual(journey.name, "Updated")
        self.assertEqual(journey.description, "New desc")

    def test_delete(self):
        journey = self._create_journey()
        journey_id = journey.id

        response = self.client.delete(f"{self.endpoint_base}{journey.id}/")

        self.assertEqual(status.HTTP_204_NO_CONTENT, response.status_code)
        self.assertFalse(
            CustomerJourney.objects.filter(id=journey_id).exists()  # nosemgrep: idor-lookup-without-team
        )

    @parameterized.expand(
        [
            (
                "create",
                lambda self: self.client.post(
                    self.endpoint_base,
                    {"insight": self.insight.id, "name": "Logged"},
                    format="json",
                ),
                "created",
            ),
            (
                "update",
                lambda self: self.client.patch(
                    f"{self.endpoint_base}{self._create_journey().id}/",
                    {"name": "Renamed"},
                    format="json",
                ),
                "updated",
            ),
            (
                "delete",
                lambda self: self.client.delete(f"{self.endpoint_base}{self._create_journey().id}/"),
                "deleted",
            ),
        ]
    )
    def test_activity_log(self, _name, perform_action, expected_activity):
        perform_action(self)

        logs = ActivityLog.objects.filter(team_id=self.team.id, scope="CustomerJourney", activity=expected_activity)
        self.assertEqual(logs.count(), 1)

    def test_unique_insight_per_team(self):
        self._create_journey()

        response = self.client.post(
            self.endpoint_base,
            {"insight": self.insight.id, "name": "Duplicate"},
            format="json",
        )

        self.assertEqual(status.HTTP_409_CONFLICT, response.status_code)
        self.assertIn("already exists", response.json()["detail"])

    def test_team_isolation(self):
        other_team = Team.objects.create(organization=self.organization)
        other_insight = Insight.objects.create(team=other_team)
        other_journey = CustomerJourney.objects.create(team=other_team, insight=other_insight, name="Other")

        response = self.client.get(f"{self.endpoint_base}{other_journey.id}/")
        self.assertEqual(status.HTTP_404_NOT_FOUND, response.status_code)

    def test_cannot_create_journey_with_other_team_insight(self):
        other_team = Team.objects.create(organization=self.organization)
        other_insight = Insight.objects.create(team=other_team)

        response = self.client.post(
            self.endpoint_base,
            {"insight": other_insight.id, "name": "Cross-team journey"},
            format="json",
        )

        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        data = response.json()
        self.assertEqual(data["attr"], "insight")
        self.assertEqual(data["detail"], "The insight does not belong to this team.")

    @parameterized.expand(
        [
            ("missing_name", lambda self: {"insight": self.insight.id}, "name"),
            ("missing_insight", lambda self: {"name": "Journey"}, "insight"),
            ("invalid_insight_id", lambda self: {"name": "Journey", "insight": 999999}, "insight"),
        ]
    )
    def test_validation_errors(self, _name, make_data, expected_error_field):
        response = self.client.post(self.endpoint_base, make_data(self), format="json")

        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        data = response.json()
        self.assertEqual(data["attr"], expected_error_field)
        self.assertEqual(data["type"], "validation_error")

    def test_authentication_required(self):
        self.client.logout()

        for method, url, expected_status_code in [
            ("GET", self.endpoint_base, status.HTTP_401_UNAUTHORIZED),
            ("POST", self.endpoint_base, status.HTTP_401_UNAUTHORIZED),
            ("GET", f"{self.endpoint_base}test-id/", status.HTTP_401_UNAUTHORIZED),
            ("PATCH", f"{self.endpoint_base}test-id/", status.HTTP_401_UNAUTHORIZED),
            ("DELETE", f"{self.endpoint_base}test-id/", status.HTTP_401_UNAUTHORIZED),
        ]:
            with self.subTest(method):
                response = getattr(self.client, method.lower())(url, format="json")
                self.assertEqual(expected_status_code, response.status_code)


class TestAccountViewSet(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.endpoint_base = f"/api/environments/{self.team.id}/accounts/"

    def _create_account(self, **kwargs):
        defaults = {"team": self.team, "name": "Acme Corp"}
        defaults.update(kwargs)
        return Account.objects.unscoped().create(**defaults)

    def test_create(self):
        response = self.client.post(
            self.endpoint_base,
            {
                "name": "Acme Corp",
                "external_id": "acme-123",
                "properties": {"csm": {"id": self.user.id, "email": self.user.email}},
            },
            format="json",
        )

        self.assertEqual(status.HTTP_201_CREATED, response.status_code, response.json())
        data = response.json()
        self.assertIn("id", data)
        self.assertEqual(data["name"], "Acme Corp")
        self.assertEqual(data["external_id"], "acme-123")
        self.assertEqual(data["properties"]["csm"], {"id": self.user.id, "email": self.user.email})
        self.assertIn("created_at", data)
        self.assertIn("updated_at", data)

        account = Account.objects.unscoped().get(id=data["id"])  # nosemgrep: idor-lookup-without-team
        self.assertEqual(account.created_by, self.user)
        self.assertEqual(account.team, self.team)
        self.assertEqual(account.properties.csm, AccountAssignment(id=self.user.id, email=self.user.email))

    def test_create_minimal_payload_uses_defaults(self):
        response = self.client.post(self.endpoint_base, {"name": "Bare Account"}, format="json")

        self.assertEqual(status.HTTP_201_CREATED, response.status_code, response.json())
        data = response.json()
        self.assertEqual(data["name"], "Bare Account")
        self.assertIsNone(data["external_id"])
        self.assertEqual(data["properties"], {})

    def test_list(self):
        a1 = self._create_account(name="Account 1")
        a2 = self._create_account(name="Account 2")

        other_team = Team.objects.create(organization=self.organization)
        Account.objects.unscoped().create(team=other_team, name="Other Team Account")

        response = self.client.get(self.endpoint_base)

        self.assertEqual(status.HTTP_200_OK, response.status_code)
        data = response.json()
        self.assertEqual(data["count"], 2)
        ids = {r["id"] for r in data["results"]}
        self.assertEqual(ids, {str(a1.id), str(a2.id)})

    def test_retrieve(self):
        account = self._create_account(
            external_id="ext-1",
            properties={"csm": {"id": self.user.id, "email": self.user.email}},
        )

        response = self.client.get(f"{self.endpoint_base}{account.id}/")

        self.assertEqual(status.HTTP_200_OK, response.status_code)
        data = response.json()
        self.assertEqual(data["id"], str(account.id))
        self.assertEqual(data["name"], "Acme Corp")
        self.assertEqual(data["external_id"], "ext-1")
        self.assertEqual(data["properties"]["csm"], {"id": self.user.id, "email": self.user.email})

    def test_update(self):
        account = self._create_account(properties={"csm": {"id": self.user.id, "email": self.user.email}})

        response = self.client.patch(
            f"{self.endpoint_base}{account.id}/",
            {
                "name": "Renamed",
                "properties": {"account_owner": {"id": self.user.id, "email": self.user.email}},
            },
            format="json",
        )

        self.assertEqual(status.HTTP_200_OK, response.status_code)
        account.refresh_from_db()
        self.assertEqual(account.name, "Renamed")
        self.assertEqual(account.properties.account_owner, AccountAssignment(id=self.user.id, email=self.user.email))

    def test_delete(self):
        account = self._create_account()
        account_id = account.id

        response = self.client.delete(f"{self.endpoint_base}{account.id}/")

        self.assertEqual(status.HTTP_204_NO_CONTENT, response.status_code)
        # nosemgrep: idor-lookup-without-team (test assertion)
        self.assertFalse(Account.objects.unscoped().filter(id=account_id).exists())

    _EXTERNAL_IDENTIFIER_PROPERTIES = {
        "stripe_customer_id": "cus_123",
        "hubspot_deal_id": "deal_456",
        "billing_id": "bill_789",
        "sfdc_id": "001A000000DUMMY",
        "zendesk_id": "zd_42",
        "slack_channel_id": "C0123456789",
        "usage_dashboard_link": "https://us.posthog.com/project/2/dashboard/12345",
    }

    def _assert_external_identifiers(self, properties_payload):
        for key, value in self._EXTERNAL_IDENTIFIER_PROPERTIES.items():
            self.assertEqual(properties_payload[key], value)

    def test_create_with_external_identifier_properties(self):
        response = self.client.post(
            self.endpoint_base,
            {"name": "Acme", "properties": self._EXTERNAL_IDENTIFIER_PROPERTIES},
            format="json",
        )

        self.assertEqual(status.HTTP_201_CREATED, response.status_code, response.json())
        self._assert_external_identifiers(response.json()["properties"])

    def test_update_with_external_identifier_properties(self):
        account = self._create_account()

        response = self.client.patch(
            f"{self.endpoint_base}{account.id}/",
            {"properties": self._EXTERNAL_IDENTIFIER_PROPERTIES},
            format="json",
        )

        self.assertEqual(status.HTTP_200_OK, response.status_code, response.json())
        self._assert_external_identifiers(response.json()["properties"])

    def test_retrieve_returns_external_identifier_properties(self):
        account = self._create_account(properties=self._EXTERNAL_IDENTIFIER_PROPERTIES)

        response = self.client.get(f"{self.endpoint_base}{account.id}/")

        self.assertEqual(status.HTTP_200_OK, response.status_code)
        self._assert_external_identifiers(response.json()["properties"])

    def test_list_returns_external_identifier_properties(self):
        self._create_account(properties=self._EXTERNAL_IDENTIFIER_PROPERTIES)

        response = self.client.get(self.endpoint_base)

        self.assertEqual(status.HTTP_200_OK, response.status_code)
        self._assert_external_identifiers(response.json()["results"][0]["properties"])

    @parameterized.expand(
        [
            (
                "create",
                lambda self: self.client.post(self.endpoint_base, {"name": "Logged"}, format="json"),
                "created",
            ),
            (
                "update",
                lambda self: self.client.patch(
                    f"{self.endpoint_base}{self._create_account().id}/",
                    {"name": "Renamed"},
                    format="json",
                ),
                "updated",
            ),
            (
                "delete",
                lambda self: self.client.delete(f"{self.endpoint_base}{self._create_account().id}/"),
                "deleted",
            ),
        ]
    )
    def test_activity_log(self, _name, perform_action, expected_activity):
        perform_action(self)

        logs = ActivityLog.objects.filter(team_id=self.team.id, scope="Account", activity=expected_activity)
        self.assertEqual(logs.count(), 1)

    def test_team_isolation(self):
        other_team = Team.objects.create(organization=self.organization)
        other_account = Account.objects.unscoped().create(team=other_team, name="Other")

        response = self.client.get(f"{self.endpoint_base}{other_account.id}/")
        self.assertEqual(status.HTTP_404_NOT_FOUND, response.status_code)

        response = self.client.patch(f"{self.endpoint_base}{other_account.id}/", {"name": "Hijacked"}, format="json")
        self.assertEqual(status.HTTP_404_NOT_FOUND, response.status_code)

        response = self.client.delete(f"{self.endpoint_base}{other_account.id}/")
        self.assertEqual(status.HTTP_404_NOT_FOUND, response.status_code)

    @parameterized.expand(
        [
            ("missing_name", {}, "name"),
            ("name_too_long", {"name": "x" * 401}, "name"),
            ("properties_not_object", {"name": "Acme", "properties": [1, 2, 3]}, "properties"),
            ("properties_not_object_string", {"name": "Acme", "properties": "not-a-dict"}, "properties"),
            (
                "properties_unknown_key",
                {"name": "Acme", "properties": {"unknown_field": "x"}},
                "properties",
            ),
            (
                "properties_assignment_missing_email",
                {"name": "Acme", "properties": {"csm": {"id": 1}}},
                "properties",
            ),
            (
                "properties_assignment_wrong_id_type",
                {"name": "Acme", "properties": {"csm": {"id": "not-an-int", "email": "a@b.co"}}},
                "properties",
            ),
        ]
    )
    def test_validation_errors(self, _name, invalid_data, expected_error_field):
        response = self.client.post(self.endpoint_base, invalid_data, format="json")

        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        data = response.json()
        self.assertEqual(data["attr"], expected_error_field)
        self.assertEqual(data["type"], "validation_error")

    def test_properties_default_when_null(self):
        response = self.client.post(self.endpoint_base, {"name": "Acme", "properties": None}, format="json")

        self.assertEqual(status.HTTP_201_CREATED, response.status_code)
        self.assertEqual({}, response.json()["properties"])

    def test_create_duplicate_external_id_returns_409(self):
        first = self.client.post(self.endpoint_base, {"name": "First", "external_id": "acme-1"}, format="json")
        self.assertEqual(status.HTTP_201_CREATED, first.status_code, first.json())

        second = self.client.post(self.endpoint_base, {"name": "Second", "external_id": "acme-1"}, format="json")

        self.assertEqual(status.HTTP_409_CONFLICT, second.status_code, second.json())
        self.assertIn("already exists", second.json()["detail"])

    def test_authentication_required(self):
        self.client.logout()

        for method, url in [
            ("GET", self.endpoint_base),
            ("POST", self.endpoint_base),
            ("GET", f"{self.endpoint_base}test-id/"),
            ("PATCH", f"{self.endpoint_base}test-id/"),
            ("DELETE", f"{self.endpoint_base}test-id/"),
        ]:
            with self.subTest(method=method, url=url):
                response = getattr(self.client, method.lower())(url, format="json")
                self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_create_with_tags(self):
        response = self.client.post(
            self.endpoint_base,
            {"name": "Tagged Account", "tags": ["enterprise", "priority"]},
            format="json",
        )

        self.assertEqual(status.HTTP_201_CREATED, response.status_code, response.json())
        self.assertEqual(sorted(response.json()["tags"]), ["enterprise", "priority"])
        # nosemgrep: idor-lookup-without-team (test assertion)
        account = Account.objects.unscoped().get(id=response.json()["id"])
        self.assertEqual(
            sorted(Tag.objects.filter(team=self.team).values_list("name", flat=True)),
            ["enterprise", "priority"],
        )
        self.assertEqual(
            sorted(TaggedItem.objects.filter(account=account).values_list("tag__name", flat=True)),
            ["enterprise", "priority"],
        )

    def test_retrieve_returns_tags(self):
        account = self._create_account()
        tag = Tag.objects.create(name="vip", team=self.team)
        account.tagged_items.create(tag=tag)

        response = self.client.get(f"{self.endpoint_base}{account.id}/")

        self.assertEqual(status.HTTP_200_OK, response.status_code)
        self.assertEqual(response.json()["tags"], ["vip"])

    def test_list_returns_tags(self):
        account = self._create_account()
        for name in ("alpha", "beta"):
            account.tagged_items.create(tag=Tag.objects.create(name=name, team=self.team))

        response = self.client.get(self.endpoint_base)

        self.assertEqual(status.HTTP_200_OK, response.status_code)
        results = {r["id"]: r for r in response.json()["results"]}
        self.assertEqual(sorted(results[str(account.id)]["tags"]), ["alpha", "beta"])

    def test_update_replaces_tags(self):
        account = self._create_account()
        account.tagged_items.create(tag=Tag.objects.create(name="old", team=self.team))

        response = self.client.patch(
            f"{self.endpoint_base}{account.id}/",
            {"tags": ["new"]},
            format="json",
        )

        self.assertEqual(status.HTTP_200_OK, response.status_code)
        self.assertEqual(response.json()["tags"], ["new"])
        self.assertEqual(list(account.tagged_items.values_list("tag__name", flat=True)), ["new"])

    def test_update_with_empty_tags_clears_them(self):
        account = self._create_account()
        account.tagged_items.create(tag=Tag.objects.create(name="stale", team=self.team))

        response = self.client.patch(f"{self.endpoint_base}{account.id}/", {"tags": []}, format="json")

        self.assertEqual(status.HTTP_200_OK, response.status_code)
        self.assertEqual(response.json()["tags"], [])
        self.assertFalse(account.tagged_items.exists())

    def test_list_filters_by_tags(self):
        billing_tag = Tag.objects.create(name="billing", team=self.team)
        urgent_tag = Tag.objects.create(name="urgent", team=self.team)
        churn_tag = Tag.objects.create(name="churn", team=self.team)

        billing = self._create_account(name="Billing Co")
        billing.tagged_items.create(tag=billing_tag)
        urgent = self._create_account(name="Urgent Co")
        urgent.tagged_items.create(tag=urgent_tag)
        churn = self._create_account(name="Churn Co")
        churn.tagged_items.create(tag=churn_tag)
        self._create_account(name="Untagged Co")

        response = self.client.get(f'{self.endpoint_base}?tags=["billing","urgent"]')

        self.assertEqual(status.HTTP_200_OK, response.status_code)
        names = {r["name"] for r in response.json()["results"]}
        self.assertEqual(names, {"Billing Co", "Urgent Co"})

    def test_list_tags_filter_returns_each_account_once_when_multiple_tags_match(self):
        billing_tag = Tag.objects.create(name="billing", team=self.team)
        urgent_tag = Tag.objects.create(name="urgent", team=self.team)
        account = self._create_account(name="Double Tagged")
        account.tagged_items.create(tag=billing_tag)
        account.tagged_items.create(tag=urgent_tag)

        response = self.client.get(f'{self.endpoint_base}?tags=["billing","urgent"]')

        self.assertEqual(status.HTTP_200_OK, response.status_code)
        self.assertEqual(response.json()["count"], 1)

    @parameterized.expand(
        [
            ("not_json", "not-json"),
            ("bare_token", "billing"),
            ("json_string", '"billing"'),
            ("json_object", '{"name":"billing"}'),
            ("list_of_ints", "[1, 2]"),
            ("mixed_list", '["billing", 1]'),
        ]
    )
    def test_list_rejects_malformed_tags_param(self, _name, tags_value):
        Tag.objects.create(name="billing", team=self.team)
        self._create_account(name="Account A")
        self._create_account(name="Account B")

        response = self.client.get(f"{self.endpoint_base}?tags={tags_value}")

        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        self.assertIn("Must be a JSON-encoded list of strings.", str(response.json()))

    def test_list_ignores_empty_tags_array(self):
        self._create_account(name="Account A")
        self._create_account(name="Account B")

        response = self.client.get(f"{self.endpoint_base}?tags=[]")

        self.assertEqual(status.HTTP_200_OK, response.status_code)
        self.assertEqual(response.json()["count"], 2)

    def test_list_with_tags_filter_does_not_n_plus_one(self):
        billing_tag = Tag.objects.create(name="billing", team=self.team)
        urgent_tag = Tag.objects.create(name="urgent", team=self.team)
        for i in range(10):
            account = self._create_account(name=f"Acct {i}")
            account.tagged_items.create(tag=billing_tag)
            account.tagged_items.create(tag=urgent_tag)

        with self.assertNumQueries(12):
            # Query budget for a tag-filtered account list. Constant regardless of result count
            # because tagged_items and notebooks are prefetched once. If a query is added, please
            # confirm it does not scale with the number of accounts before raising the limit:
            # 1: load Django session
            # 2: load authenticated user
            # 3: load user's current organization
            # 4: load team for the requested project
            # 5: load org membership for permission checks
            # 6: load RBAC access controls for customer_analytics
            # 7: load org membership again for role inheritance
            # 8: load constance instance setting (rate limit config)
            # 9: COUNT(*) for pagination
            # 10: SELECT page of accounts filtered by tag name
            # 11: prefetch resourcenotebook (joined with notebook) for the page
            # 12: prefetch tagged_items + tag for the page (the prefetch that prevents N+1)
            response = self.client.get(f'{self.endpoint_base}?tags=["billing","urgent"]')

        self.assertEqual(status.HTTP_200_OK, response.status_code)
        self.assertEqual(response.json()["count"], 10)

    def test_tag_change_logs_to_account_activity_stream(self):
        account = self._create_account()
        initial_logs = ActivityLog.objects.filter(team_id=self.team.id, scope="Account", activity="updated").count()

        response = self.client.patch(f"{self.endpoint_base}{account.id}/", {"tags": ["audit"]}, format="json")
        self.assertEqual(status.HTTP_200_OK, response.status_code)

        new_logs = ActivityLog.objects.filter(team_id=self.team.id, scope="Account", activity="updated").count()
        self.assertGreater(new_logs, initial_logs)

    def test_list_accounts_filter_by_csm_user_id(self):
        self._create_account(name="A", _properties={"csm": {"id": 7, "email": "a@x.com"}})
        self._create_account(name="B", _properties={"csm": {"id": 9, "email": "b@x.com"}})
        response = self.client.get(f"/api/environments/{self.team.id}/accounts/?csm=7")
        names = [r["name"] for r in response.json()["results"]]
        assert names == ["A"]

    @parameterized.expand(
        [
            # `_properties` defaults to {} — every role key is absent.
            ("absent_keys", {"_properties": {}}),
            # The manager fills every role key with an explicit JSON null.
            ("null_valued_keys", {"properties": {}}),
        ]
    )
    def test_list_accounts_filter_by_csm_unassigned(self, _name, unassigned_kwargs):
        self._create_account(name="Assigned", properties={"csm": {"id": 7, "email": "a@x.com"}})
        self._create_account(name="Unassigned", **unassigned_kwargs)
        response = self.client.get(f"{self.endpoint_base}?csm=unassigned")
        assert [r["name"] for r in response.json()["results"]] == ["Unassigned"]

    def test_list_accounts_filter_by_account_executive_user_id(self):
        self._create_account(name="A", _properties={"account_executive": {"id": 7, "email": "a@x.com"}})
        self._create_account(name="B")
        response = self.client.get(f"/api/environments/{self.team.id}/accounts/?account_executive=7")
        assert [r["name"] for r in response.json()["results"]] == ["A"]

    def test_list_accounts_filter_by_account_owner_user_id(self):
        self._create_account(name="A", _properties={"account_owner": {"id": 7, "email": "a@x.com"}})
        self._create_account(name="B")
        response = self.client.get(f"/api/environments/{self.team.id}/accounts/?account_owner=7")
        assert [r["name"] for r in response.json()["results"]] == ["A"]

    @parameterized.expand(
        [
            # `_properties` defaults to {} — every role key is absent.
            ("absent_keys", {"_properties": {}}),
            # The manager fills every role key with an explicit JSON null.
            ("null_valued_keys", {"properties": {}}),
        ]
    )
    def test_list_accounts_filter_all_roles_unassigned(self, _name, unassigned_kwargs):
        # Created through the manager, so every role key is present and csm has a real id.
        self._create_account(name="Has CSM", properties={"csm": {"id": 7, "email": "a@x.com"}})
        self._create_account(name="Unassigned", **unassigned_kwargs)
        response = self.client.get(f"{self.endpoint_base}?all_roles_unassigned=true")
        assert [r["name"] for r in response.json()["results"]] == ["Unassigned"]

    def test_list_accounts_filter_combined_role_and_tags(self):
        account_a = self._create_account(name="A", _properties={"csm": {"id": 7, "email": "a@x.com"}})
        account_b = self._create_account(name="B", _properties={"csm": {"id": 7, "email": "a@x.com"}})
        account_c = self._create_account(name="C", _properties={"csm": {"id": 8, "email": "c@x.com"}})
        set_tags_on_object(["enterprise"], account_a)
        set_tags_on_object(["startup"], account_b)
        set_tags_on_object(["enterprise"], account_c)
        response = self.client.get(f'/api/environments/{self.team.id}/accounts/?csm=7&tags=["enterprise"]')
        assert [r["name"] for r in response.json()["results"]] == ["A"]

    def test_list_accounts_invalid_csm_value_is_ignored(self):
        # Malformed user id should be a no-op (return both accounts), not "match nothing".
        self._create_account(name="A")
        self._create_account(name="B", _properties={"csm": {"id": 7, "email": "b@x.com"}})
        response = self.client.get(f"/api/environments/{self.team.id}/accounts/?csm=not-a-user")
        assert response.status_code == status.HTTP_200_OK
        names = sorted(r["name"] for r in response.json()["results"])
        assert names == ["A", "B"]

    def test_list_accounts_ordering_by_name_asc(self):
        # Create in alphabetical order so default `-created_at` order is [Banana, Apple];
        # ordering=name only matches if the filter actually flips the order.
        self._create_account(name="Apple")
        self._create_account(name="Banana")
        response = self.client.get(f"/api/environments/{self.team.id}/accounts/?ordering=name")
        assert [r["name"] for r in response.json()["results"]] == ["Apple", "Banana"]

    def test_list_accounts_ordering_by_name_desc(self):
        # Default `-created_at` order would be [Apple, Banana]; ordering=-name flips to [Banana, Apple].
        self._create_account(name="Banana")
        self._create_account(name="Apple")
        response = self.client.get(f"/api/environments/{self.team.id}/accounts/?ordering=-name")
        assert [r["name"] for r in response.json()["results"]] == ["Banana", "Apple"]

    def test_list_accounts_invalid_ordering_is_ignored(self):
        # Malformed ordering should fall back to default `-created_at` order.
        self._create_account(name="Apple")
        self._create_account(name="Banana")
        response = self.client.get(f"/api/environments/{self.team.id}/accounts/?ordering=robert');drop")
        assert response.status_code == status.HTTP_200_OK
        assert [r["name"] for r in response.json()["results"]] == ["Banana", "Apple"]

    @parameterized.expand(
        [
            ("name_exact", "Acme Corp", ["Acme Corp"]),
            ("name_partial_case_insensitive", "acme", ["Acme Corp"]),
            ("external_id_partial", "glx-9", ["Globex"]),
            ("matches_name_or_external_id", "1", ["Acme Corp"]),
            ("no_match", "zzzz", []),
        ]
    )
    def test_list_accounts_search(self, _name, search, expected):
        self._create_account(name="Acme Corp", external_id="acme-1")
        self._create_account(name="Globex", external_id="glx-99")
        response = self.client.get(f"{self.endpoint_base}?search={search}")
        assert response.status_code == status.HTTP_200_OK
        assert sorted(r["name"] for r in response.json()["results"]) == sorted(expected)

    def test_list_accounts_blank_search_returns_all(self):
        self._create_account(name="Acme Corp")
        self._create_account(name="Globex")
        response = self.client.get(f"{self.endpoint_base}?search=")
        assert sorted(r["name"] for r in response.json()["results"]) == ["Acme Corp", "Globex"]

    def test_list_accounts_search_respects_team_isolation(self):
        other_team = Team.objects.create(organization=self.organization, name="other")
        self._create_account(team=other_team, name="Acme Corp")
        self._create_account(name="Acme Corp")
        response = self.client.get(f"{self.endpoint_base}?search=acme")
        assert len(response.json()["results"]) == 1

    def test_list_accounts_role_filter_respects_team_isolation(self):
        other_team = Team.objects.create(organization=self.organization, name="other")
        self._create_account(
            team=other_team,
            name="OtherTeamAccount",
            _properties={"csm": {"id": 7, "email": "a@x.com"}},
        )
        self._create_account(name="MyAccount", _properties={"csm": {"id": 7, "email": "a@x.com"}})
        response = self.client.get(f"/api/environments/{self.team.id}/accounts/?csm=7")
        assert [r["name"] for r in response.json()["results"]] == ["MyAccount"]

    def test_retrieve_returns_empty_notebooks_when_none_linked(self):
        account = self._create_account()

        response = self.client.get(f"{self.endpoint_base}{account.id}/")

        self.assertEqual(status.HTTP_200_OK, response.status_code)
        self.assertEqual(response.json()["notebooks"], [])

    def test_retrieve_returns_all_linked_notebooks(self):
        account = self._create_account()
        notebook_a = Notebook.objects.create(
            team=self.team, title="A", content=[], visibility=Notebook.Visibility.INTERNAL
        )
        notebook_b = Notebook.objects.create(
            team=self.team, title="B", content=[], visibility=Notebook.Visibility.INTERNAL
        )
        ResourceNotebook.objects.create(notebook=notebook_a, account=account)
        ResourceNotebook.objects.create(notebook=notebook_b, account=account)

        response = self.client.get(f"{self.endpoint_base}{account.id}/")

        self.assertEqual(status.HTTP_200_OK, response.status_code)
        self.assertEqual(set(response.json()["notebooks"]), {notebook_a.short_id, notebook_b.short_id})

    def test_list_includes_notebooks_field(self):
        account = self._create_account()
        notebook = Notebook.objects.create(
            team=self.team, title="Existing", content=[], visibility=Notebook.Visibility.INTERNAL
        )
        ResourceNotebook.objects.create(notebook=notebook, account=account)

        response = self.client.get(self.endpoint_base)

        self.assertEqual(status.HTTP_200_OK, response.status_code)
        result = next(r for r in response.json()["results"] if r["id"] == str(account.id))
        self.assertEqual(result["notebooks"], [notebook.short_id])


class TestAccountNotebookViewSet(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.account = Account.objects.unscoped().create(team=self.team, name="Acme Corp")
        self.endpoint_base = f"/api/environments/{self.team.id}/accounts/{self.account.id}/notebooks/"

    def test_create_account_notebook_uses_internal_visibility(self):
        response = self.client.post(
            self.endpoint_base,
            {"title": "Q3 call", "content": {"type": "doc", "content": []}},
            format="json",
        )

        self.assertEqual(status.HTTP_201_CREATED, response.status_code, response.json())
        data = response.json()
        self.assertIn("short_id", data)
        self.assertEqual(data["title"], "Q3 call")

        # nosemgrep: idor-lookup-without-team (test assertion)
        notebook = Notebook.objects.get(short_id=data["short_id"])
        self.assertEqual(notebook.team, self.team)
        self.assertEqual(notebook.visibility, Notebook.Visibility.INTERNAL)
        self.assertEqual(notebook.created_by, self.user)

        self.assertTrue(
            ResourceNotebook.objects.filter(notebook=notebook, account=self.account).exists(),
        )

    def test_list_returns_only_notebooks_for_account(self):
        account_notebook = Notebook.objects.create(
            team=self.team, title="Account note", content={}, visibility=Notebook.Visibility.INTERNAL
        )
        ResourceNotebook.objects.create(notebook=account_notebook, account=self.account)

        other_account = Account.objects.unscoped().create(team=self.team, name="Other")
        other_notebook = Notebook.objects.create(
            team=self.team, title="Other note", content={}, visibility=Notebook.Visibility.INTERNAL
        )
        ResourceNotebook.objects.create(notebook=other_notebook, account=other_account)

        Notebook.objects.create(team=self.team, title="Standalone", content={}, visibility=Notebook.Visibility.DEFAULT)

        response = self.client.get(self.endpoint_base)

        self.assertEqual(status.HTTP_200_OK, response.status_code)
        short_ids = [n["short_id"] for n in response.json()["results"]]
        self.assertEqual(short_ids, [account_notebook.short_id])

    def _link_internal_notebook(self, **kwargs) -> Notebook:
        notebook = Notebook.objects.create(team=self.team, visibility=Notebook.Visibility.INTERNAL, **kwargs)
        ResourceNotebook.objects.create(notebook=notebook, account=self.account)
        return notebook

    def test_list_search_matches_title_and_content(self):
        by_title = self._link_internal_notebook(title="Renewal planning", text_content="")
        by_content = self._link_internal_notebook(title="Untitled", text_content="discuss renewal terms")
        self._link_internal_notebook(title="Onboarding", text_content="kickoff call")

        response = self.client.get(f"{self.endpoint_base}?search=renewal")

        self.assertEqual(status.HTTP_200_OK, response.status_code)
        short_ids = {n["short_id"] for n in response.json()["results"]}
        self.assertEqual(short_ids, {by_title.short_id, by_content.short_id})

    def test_list_orders_by_created_at(self):
        with freeze_time("2024-01-01"):
            older = self._link_internal_notebook(title="Older", content={})
        with freeze_time("2024-01-02"):
            newer = self._link_internal_notebook(title="Newer", content={})

        default_order = [n["short_id"] for n in self.client.get(self.endpoint_base).json()["results"]]
        self.assertEqual(default_order, [newer.short_id, older.short_id])

        ascending = [
            n["short_id"] for n in self.client.get(f"{self.endpoint_base}?ordering=created_at").json()["results"]
        ]
        self.assertEqual(ascending, [older.short_id, newer.short_id])

    def test_retrieve_returns_notebook_for_account(self):
        notebook = Notebook.objects.create(
            team=self.team, title="Note", content={"foo": "bar"}, visibility=Notebook.Visibility.INTERNAL
        )
        ResourceNotebook.objects.create(notebook=notebook, account=self.account)

        response = self.client.get(f"{self.endpoint_base}{notebook.short_id}/")

        self.assertEqual(status.HTTP_200_OK, response.status_code)
        data = response.json()
        self.assertEqual(data["short_id"], notebook.short_id)
        self.assertEqual(data["title"], "Note")
        self.assertEqual(data["content"], {"foo": "bar"})

    def test_retrieve_notebook_not_linked_to_account_returns_404(self):
        unrelated = Notebook.objects.create(
            team=self.team, title="Unrelated", content={}, visibility=Notebook.Visibility.DEFAULT
        )

        response = self.client.get(f"{self.endpoint_base}{unrelated.short_id}/")

        self.assertEqual(status.HTTP_404_NOT_FOUND, response.status_code)

    def test_destroy_notebook_for_account(self):
        notebook = Notebook.objects.create(
            team=self.team, title="Note", content={}, visibility=Notebook.Visibility.INTERNAL
        )
        ResourceNotebook.objects.create(notebook=notebook, account=self.account)
        notebook_pk = notebook.pk

        response = self.client.delete(f"{self.endpoint_base}{notebook.short_id}/")

        self.assertEqual(status.HTTP_204_NO_CONTENT, response.status_code)
        # nosemgrep: idor-lookup-without-team (test assertion)
        self.assertFalse(Notebook.objects.filter(pk=notebook_pk).exists())
        self.assertFalse(ResourceNotebook.objects.filter(account=self.account).exists())

    def test_create_for_unknown_account_returns_404(self):
        bad_url = f"/api/environments/{self.team.id}/accounts/00000000-0000-0000-0000-000000000000/notebooks/"

        response = self.client.post(bad_url, {"title": "X"}, format="json")

        self.assertEqual(status.HTTP_404_NOT_FOUND, response.status_code)

    def test_other_team_account_is_not_accessible(self):
        other_team = Team.objects.create(organization=self.organization)
        other_account = Account.objects.unscoped().create(team=other_team, name="Other team")

        url = f"/api/environments/{self.team.id}/accounts/{other_account.id}/notebooks/"
        response = self.client.post(url, {"title": "X"}, format="json")

        self.assertEqual(status.HTTP_404_NOT_FOUND, response.status_code)

    def test_internal_account_notebooks_do_not_appear_in_notebooks_list(self):
        notebook = Notebook.objects.create(
            team=self.team, title="Account note", content={}, visibility=Notebook.Visibility.INTERNAL
        )
        ResourceNotebook.objects.create(notebook=notebook, account=self.account)

        response = self.client.get(f"/api/projects/{self.team.id}/notebooks/")
        self.assertEqual(status.HTTP_200_OK, response.status_code)
        short_ids = [n["short_id"] for n in response.json()["results"]]
        self.assertNotIn(notebook.short_id, short_ids)

    def test_authentication_required(self):
        self.client.logout()

        for method, url in [
            ("GET", self.endpoint_base),
            ("POST", self.endpoint_base),
            ("GET", f"{self.endpoint_base}abc123/"),
            ("DELETE", f"{self.endpoint_base}abc123/"),
        ]:
            with self.subTest(method=method, url=url):
                response = getattr(self.client, method.lower())(url, format="json")
                self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_list_excludes_non_internal_notebooks_linked_to_account(self):
        internal_notebook = Notebook.objects.create(
            team=self.team, title="Internal", content={}, visibility=Notebook.Visibility.INTERNAL
        )
        ResourceNotebook.objects.create(notebook=internal_notebook, account=self.account)

        default_notebook = Notebook.objects.create(
            team=self.team, title="Default", content={}, visibility=Notebook.Visibility.DEFAULT
        )
        ResourceNotebook.objects.create(notebook=default_notebook, account=self.account)

        response = self.client.get(self.endpoint_base)

        self.assertEqual(status.HTTP_200_OK, response.status_code)
        short_ids = [n["short_id"] for n in response.json()["results"]]
        self.assertIn(internal_notebook.short_id, short_ids)
        self.assertNotIn(default_notebook.short_id, short_ids)

    def test_create_derives_content_from_markdown_text_content(self):
        response = self.client.post(
            self.endpoint_base,
            {"title": "Call notes", "text_content": "# Heading\n\nSome **bold** text."},
            format="json",
        )

        self.assertEqual(status.HTTP_201_CREATED, response.status_code, response.json())
        # nosemgrep: idor-lookup-without-team (test assertion)
        notebook = Notebook.objects.get(short_id=response.json()["short_id"])
        self.assertEqual(notebook.text_content, "# Heading\n\nSome **bold** text.")
        self.assertIsInstance(notebook.content, dict)
        self.assertEqual(notebook.content["type"], "doc")
        first_node = notebook.content["content"][0]
        self.assertEqual(first_node["type"], "heading")
        self.assertEqual(first_node["attrs"]["level"], 1)
        self.assertEqual(first_node["content"][0]["text"], "Heading")

    def test_create_preserves_caller_supplied_content(self):
        explicit_content = {
            "type": "doc",
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": "from caller"}]}],
        }
        response = self.client.post(
            self.endpoint_base,
            {"title": "Provided", "content": explicit_content, "text_content": "# ignored"},
            format="json",
        )

        self.assertEqual(status.HTTP_201_CREATED, response.status_code, response.json())
        # nosemgrep: idor-lookup-without-team (test assertion)
        notebook = Notebook.objects.get(short_id=response.json()["short_id"])
        self.assertEqual(notebook.content, explicit_content)

    def test_create_with_neither_field_leaves_content_null(self):
        response = self.client.post(self.endpoint_base, {"title": "Empty"}, format="json")

        self.assertEqual(status.HTTP_201_CREATED, response.status_code, response.json())
        # nosemgrep: idor-lookup-without-team (test assertion)
        notebook = Notebook.objects.get(short_id=response.json()["short_id"])
        self.assertIsNone(notebook.content)

    def test_create_with_empty_text_content_does_not_synthesize_content(self):
        response = self.client.post(
            self.endpoint_base,
            {"title": "Empty body", "text_content": ""},
            format="json",
        )

        self.assertEqual(status.HTTP_201_CREATED, response.status_code, response.json())
        # nosemgrep: idor-lookup-without-team (test assertion)
        notebook = Notebook.objects.get(short_id=response.json()["short_id"])
        self.assertIsNone(notebook.content)

    def test_create_with_empty_dict_content_falls_back_to_markdown(self):
        response = self.client.post(
            self.endpoint_base,
            {"title": "Plain", "content": {}, "text_content": "Just a sentence."},
            format="json",
        )

        self.assertEqual(status.HTTP_201_CREATED, response.status_code, response.json())
        # nosemgrep: idor-lookup-without-team (test assertion)
        notebook = Notebook.objects.get(short_id=response.json()["short_id"])
        self.assertEqual(notebook.content["type"], "doc")
        first_node = notebook.content["content"][0]
        self.assertEqual(first_node["type"], "paragraph")
        self.assertEqual(first_node["content"][0]["text"], "Just a sentence.")

    def test_create_with_empty_valid_prosemirror_doc_respects_caller(self):
        empty_doc = {"type": "doc", "content": []}
        response = self.client.post(
            self.endpoint_base,
            {"title": "Empty doc", "content": empty_doc, "text_content": "ignored"},
            format="json",
        )

        self.assertEqual(status.HTTP_201_CREATED, response.status_code, response.json())
        # nosemgrep: idor-lookup-without-team (test assertion)
        notebook = Notebook.objects.get(short_id=response.json()["short_id"])
        self.assertEqual(notebook.content, empty_doc)

    def test_notebook_detail_includes_parent_resource_for_linked_account(self):
        notebook = Notebook.objects.create(
            team=self.team, title="Account note", content={}, visibility=Notebook.Visibility.INTERNAL
        )
        ResourceNotebook.objects.create(notebook=notebook, account=self.account)

        # The frontend NotebookScene fetches via /api/projects/{team}/notebooks/{short_id}/
        # (not the customer-analytics nested endpoint), so the parent_resource field must be
        # present on NotebookSerializer responses.
        response = self.client.get(f"/api/projects/{self.team.id}/notebooks/{notebook.short_id}/")

        self.assertEqual(status.HTTP_200_OK, response.status_code, response.json())
        self.assertEqual(
            response.json()["parent_resource"],
            {"type": "account", "id": str(self.account.id)},
        )

    def test_notebook_detail_parent_resource_is_null_for_standalone(self):
        notebook = Notebook.objects.create(
            team=self.team, title="Standalone", content={}, visibility=Notebook.Visibility.DEFAULT
        )

        response = self.client.get(f"/api/projects/{self.team.id}/notebooks/{notebook.short_id}/")

        self.assertEqual(status.HTTP_200_OK, response.status_code, response.json())
        self.assertIsNone(response.json()["parent_resource"])


@pytest.mark.ee
class TestCustomerAnalyticsAccessControl(APIBaseTest):
    """Resource-level access control tests for customer journeys and accounts.

    Note: CustomerProfileConfig is a settings resource and uses project-level
    admin permissions, not resource-level RBAC. See TestCustomerProfileConfigViewSet
    for those tests.
    """

    def setUp(self):
        super().setUp()

        self.organization.available_product_features = [
            {
                "key": AvailableFeature.ACCESS_CONTROL,
                "name": AvailableFeature.ACCESS_CONTROL,
            },
            {
                "key": AvailableFeature.ROLE_BASED_ACCESS,
                "name": AvailableFeature.ROLE_BASED_ACCESS,
            },
        ]
        self.organization.save()

        self.viewer_user = User.objects.create_and_join(self.organization, "viewer@posthog.com", "testtest")
        self.editor_user = User.objects.create_and_join(self.organization, "editor@posthog.com", "testtest")
        self.no_access_user = User.objects.create_and_join(self.organization, "noaccess@posthog.com", "testtest")

        self.insight = Insight.objects.create(team=self.team)
        self.journey = CustomerJourney.objects.create(
            team=self.team,
            insight=self.insight,
            name="Test Journey",
        )

        self.journeys_url = f"/api/environments/{self.team.id}/customer_journeys/"

        self.account = Account.objects.unscoped().create(team=self.team, name="ACL Account")
        self.accounts_url = f"/api/environments/{self.team.id}/accounts/"

    def _set_access_level(self, user: User, resource: str = "customer_analytics", access_level: str = "viewer") -> None:
        try:
            membership = OrganizationMembership.objects.get(user=user, organization=self.organization)
            AccessControl.objects.create(
                team=self.team,
                resource=resource,
                resource_id=None,
                access_level=access_level,
                organization_member=membership,
            )
        except:
            pass

    # -- Viewer can list and retrieve journeys --

    def test_viewer_can_list_journeys(self):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.get(self.journeys_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_viewer_can_retrieve_journey(self):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.get(f"{self.journeys_url}{self.journey.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    # -- Viewer cannot create/update/delete journeys --

    def test_viewer_cannot_create_journey(self):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        insight2 = Insight.objects.create(team=self.team)
        response = self.client.post(
            self.journeys_url,
            {"insight": insight2.id, "name": "New Journey"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_update_journey(self):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.patch(
            f"{self.journeys_url}{self.journey.id}/",
            {"name": "Updated"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_delete_journey(self):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.delete(f"{self.journeys_url}{self.journey.id}/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # -- Editor can create/update/delete journeys --

    def test_editor_can_create_journey(self):
        self._set_access_level(self.editor_user, access_level="editor")
        self.client.force_login(self.editor_user)

        insight2 = Insight.objects.create(team=self.team)
        response = self.client.post(
            self.journeys_url,
            {"insight": insight2.id, "name": "Editor Journey"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_editor_can_update_journey(self):
        self._set_access_level(self.editor_user, access_level="editor")
        self.client.force_login(self.editor_user)

        response = self.client.patch(
            f"{self.journeys_url}{self.journey.id}/",
            {"name": "Updated by editor"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_editor_can_delete_journey(self):
        self._set_access_level(self.editor_user, access_level="editor")
        self.client.force_login(self.editor_user)

        response = self.client.delete(f"{self.journeys_url}{self.journey.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    # -- None access blocks everything --

    def test_none_access_blocks_journey_list(self):
        self._set_access_level(self.no_access_user, access_level="none")
        self.client.force_login(self.no_access_user)

        response = self.client.get(self.journeys_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # -- Resource inheritance: customer_analytics access cascades to journeys --

    def test_customer_analytics_viewer_can_list_journeys(self):
        self._set_access_level(self.viewer_user, resource="customer_analytics", access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.get(self.journeys_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_customer_analytics_none_blocks_journey_list(self):
        self._set_access_level(self.no_access_user, resource="customer_analytics", access_level="none")
        self.client.force_login(self.no_access_user)

        response = self.client.get(self.journeys_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_customer_analytics_editor_can_create_journey(self):
        self._set_access_level(self.editor_user, resource="customer_analytics", access_level="editor")
        self.client.force_login(self.editor_user)

        insight2 = Insight.objects.create(team=self.team)
        response = self.client.post(
            self.journeys_url,
            {"insight": insight2.id, "name": "Child Journey"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_customer_analytics_viewer_cannot_create_journey(self):
        self._set_access_level(self.viewer_user, resource="customer_analytics", access_level="viewer")
        self.client.force_login(self.viewer_user)

        insight2 = Insight.objects.create(team=self.team)
        response = self.client.post(
            self.journeys_url,
            {"insight": insight2.id, "name": "Should Fail"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # -- Org admin has full access without explicit permissions --

    def test_org_admin_has_full_access(self):
        membership = OrganizationMembership.objects.get(user=self.editor_user, organization=self.organization)
        membership.level = OrganizationMembership.Level.ADMIN
        membership.save()

        self.client.force_login(self.editor_user)

        insight2 = Insight.objects.create(team=self.team)
        response = self.client.post(
            self.journeys_url,
            {"insight": insight2.id, "name": "Admin Journey"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        response = self.client.delete(f"{self.journeys_url}{self.journey.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    # -- Resource inheritance: customer_analytics access cascades to accounts --

    def test_customer_analytics_viewer_can_list_accounts(self):
        self._set_access_level(self.viewer_user, resource="customer_analytics", access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.get(self.accounts_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_customer_analytics_viewer_cannot_create_account(self):
        self._set_access_level(self.viewer_user, resource="customer_analytics", access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.post(self.accounts_url, {"name": "Should Fail"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_customer_analytics_editor_can_create_account(self):
        self._set_access_level(self.editor_user, resource="customer_analytics", access_level="editor")
        self.client.force_login(self.editor_user)

        response = self.client.post(self.accounts_url, {"name": "Inherited Account"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_customer_analytics_none_blocks_account_list(self):
        self._set_access_level(self.no_access_user, resource="customer_analytics", access_level="none")
        self.client.force_login(self.no_access_user)

        response = self.client.get(self.accounts_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # -- Account notebooks inherit object-level access from the parent account --

    def test_account_notebooks_404_when_parent_account_access_denied(self):
        AccessControl.objects.create(
            team=self.team,
            resource="account",
            resource_id=str(self.account.id),
            access_level="none",
            organization_member=OrganizationMembership.objects.get(
                user=self.viewer_user, organization=self.organization
            ),
        )
        self._set_access_level(self.viewer_user, resource="account", access_level="viewer")
        self.client.force_login(self.viewer_user)

        url = f"{self.accounts_url}{self.account.id}/notebooks/"

        list_response = self.client.get(url)
        self.assertEqual(list_response.status_code, status.HTTP_404_NOT_FOUND)

        create_response = self.client.post(url, {"title": "x"}, format="json")
        self.assertEqual(create_response.status_code, status.HTTP_404_NOT_FOUND)


class TestCustomPropertyDefinitionViewSet(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.endpoint_base = f"/api/environments/{self.team.id}/custom_property_definitions/"

    def _create(self, **overrides):
        payload = {"name": "ARR", "display_type": "currency", "is_big_number": True}
        payload.update(overrides)
        return self.client.post(self.endpoint_base, payload, format="json")

    def test_create_success(self):
        response = self._create()

        self.assertEqual(status.HTTP_201_CREATED, response.status_code, response.json())
        data = response.json()
        self.assertEqual(data["name"], "ARR")
        self.assertEqual(data["display_type"], "currency")
        self.assertTrue(data["is_big_number"])
        self.assertIn("id", data)
        self.assertIn("created_at", data)

        # nosemgrep: idor-lookup-without-team (test assertion)
        definition = CustomPropertyDefinition.objects.unscoped().get(id=data["id"])
        self.assertEqual(definition.team, self.team)
        self.assertEqual(definition.created_by, self.user)

    def test_create_text_property(self):
        response = self._create(name="Tier", display_type="text", is_big_number=False)

        self.assertEqual(status.HTTP_201_CREATED, response.status_code, response.json())
        self.assertEqual(response.json()["display_type"], "text")

    @parameterized.expand(
        [
            ("text", "text", status.HTTP_201_CREATED),
            ("number", "number", status.HTTP_201_CREATED),
            ("currency", "currency", status.HTTP_201_CREATED),
            ("percent", "percent", status.HTTP_201_CREATED),
            ("date", "date", status.HTTP_201_CREATED),
            ("datetime", "datetime", status.HTTP_201_CREATED),
            ("boolean", "boolean", status.HTTP_201_CREATED),
            ("unknown_rejected", "frobnicate", status.HTTP_400_BAD_REQUEST),
        ]
    )
    def test_display_type_validation(self, _name, display_type, expected_status):
        response = self.client.post(self.endpoint_base, {"name": "P", "display_type": display_type}, format="json")
        self.assertEqual(expected_status, response.status_code, response.json())

    def test_create_select_assigns_option_ids_and_patch_round_trips(self):
        response = self._create(
            name="Stage",
            display_type="select",
            is_big_number=False,
            options=[{"label": "Open", "color": "preset-1"}, {"label": "Closed", "color": "preset-2"}],
        )

        self.assertEqual(status.HTTP_201_CREATED, response.status_code, response.json())
        options = response.json()["options"]
        self.assertEqual([option["label"] for option in options], ["Open", "Closed"])
        self.assertTrue(all(option["id"] for option in options))

        patched = self.client.patch(
            f"{self.endpoint_base}{response.json()['id']}/",
            {"options": [{**options[0], "label": "Won"}, options[1]]},
            format="json",
        )

        self.assertEqual(status.HTTP_200_OK, patched.status_code, patched.json())
        self.assertEqual([option["label"] for option in patched.json()["options"]], ["Won", "Closed"])
        self.assertEqual(patched.json()["options"][0]["id"], options[0]["id"])

    @parameterized.expand(
        [
            ("select_without_options", {"name": "S1", "display_type": "select"}),
            ("select_empty_options", {"name": "S2", "display_type": "select", "options": []}),
            ("bad_color", {"name": "S3", "display_type": "select", "options": [{"label": "A", "color": "red"}]}),
        ]
    )
    def test_create_select_rejects_invalid_payloads(self, _name, payload):
        response = self.client.post(self.endpoint_base, payload, format="json")

        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code, response.json())

    def test_is_big_number_forced_false_for_non_numeric(self):
        response = self._create(name="Tier", display_type="text", is_big_number=True)

        self.assertEqual(status.HTTP_201_CREATED, response.status_code, response.json())
        self.assertFalse(response.json()["is_big_number"])

    def test_create_with_duplicate_name_returns_409(self):
        self._create(name="ARR")

        response = self._create(name="ARR")

        self.assertEqual(status.HTTP_409_CONFLICT, response.status_code, response.json())

    def test_list_returns_only_current_team_ordered_by_name(self):
        self._create(name="Beta", display_type="text")
        self._create(name="Alpha", display_type="text")
        other_team = Team.objects.create(organization=self.organization)
        # nosemgrep: idor-lookup-without-team (test setup for another team)
        CustomPropertyDefinition.objects.unscoped().create(team=other_team, name="Gamma", display_type="text")

        response = self.client.get(self.endpoint_base)

        self.assertEqual(status.HTTP_200_OK, response.status_code)
        self.assertEqual([row["name"] for row in response.json()["results"]], ["Alpha", "Beta"])

    def test_update_name(self):
        created = self._create(name="ARR").json()

        response = self.client.patch(f"{self.endpoint_base}{created['id']}/", {"name": "Annual revenue"}, format="json")

        self.assertEqual(status.HTTP_200_OK, response.status_code, response.json())
        self.assertEqual(response.json()["name"], "Annual revenue")

    def test_update_to_duplicate_name_returns_409(self):
        self._create(name="ARR")
        other = self._create(name="MRR").json()

        response = self.client.patch(f"{self.endpoint_base}{other['id']}/", {"name": "ARR"}, format="json")

        self.assertEqual(status.HTTP_409_CONFLICT, response.status_code, response.json())

    def test_display_type_is_editable(self):
        created = self._create(name="Field", display_type="text").json()

        response = self.client.patch(
            f"{self.endpoint_base}{created['id']}/",
            {"name": "Field", "display_type": "number", "is_big_number": False},
            format="json",
        )

        self.assertEqual(status.HTTP_200_OK, response.status_code, response.json())
        self.assertEqual(response.json()["display_type"], "number")

    def test_patch_display_type_without_other_fields(self):
        created = self._create(name="Field", display_type="currency").json()

        response = self.client.patch(f"{self.endpoint_base}{created['id']}/", {"display_type": "text"}, format="json")

        self.assertEqual(status.HTTP_200_OK, response.status_code, response.json())
        self.assertEqual(response.json()["display_type"], "text")

    def test_delete_removes_definition_only(self):
        keep = self._create(name="Keep", display_type="text").json()
        remove = self._create(name="Remove", display_type="text").json()

        response = self.client.delete(f"{self.endpoint_base}{remove['id']}/")

        self.assertEqual(status.HTTP_204_NO_CONTENT, response.status_code)
        # nosemgrep: idor-lookup-without-team (test assertion)
        self.assertFalse(CustomPropertyDefinition.objects.unscoped().filter(id=remove["id"]).exists())
        # nosemgrep: idor-lookup-without-team (test assertion)
        self.assertTrue(CustomPropertyDefinition.objects.unscoped().filter(id=keep["id"]).exists())

    def test_cannot_access_other_teams_definition(self):
        other_team = Team.objects.create(organization=self.organization)
        # nosemgrep: idor-lookup-without-team (test setup for another team)
        other_def = CustomPropertyDefinition.objects.unscoped().create(
            team=other_team, name="Other", display_type="text"
        )

        response = self.client.get(f"{self.endpoint_base}{other_def.id}/")

        self.assertEqual(status.HTTP_404_NOT_FOUND, response.status_code)

    def test_activity_log_on_create_and_delete(self):
        created = self._create(name="ARR").json()
        self.client.delete(f"{self.endpoint_base}{created['id']}/")

        logs = ActivityLog.objects.filter(
            team_id=self.team.id, scope="CustomPropertyDefinition", item_id=str(created["id"])
        )
        self.assertEqual(set(logs.values_list("activity", flat=True)), {"created", "deleted"})


class TestCustomPropertyDefinitionAccessControl(APIBaseTest):
    """Resource-level access control for custom property definitions.

    Definitions are a team-wide ``account``-resource config (no per-object ownership), so they are
    gated at the resource level by the default ``AccessControlPermission`` (keyed on
    ``scope_object="account"``) — the same gate as accounts and journeys, including inheritance from
    the ``customer_analytics`` parent resource. Reads need ``viewer``, writes need ``editor``.
    """

    def setUp(self):
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()

        self.viewer_user = User.objects.create_and_join(self.organization, "def-viewer@posthog.com", "testtest")
        self.editor_user = User.objects.create_and_join(self.organization, "def-editor@posthog.com", "testtest")
        self.no_access_user = User.objects.create_and_join(self.organization, "def-noaccess@posthog.com", "testtest")

        # nosemgrep: idor-lookup-without-team (test setup)
        self.definition = CustomPropertyDefinition.objects.unscoped().create(
            team=self.team, name="ARR", display_type="currency"
        )
        self.endpoint_base = f"/api/environments/{self.team.id}/custom_property_definitions/"

    def _set_access_level(self, user: User, resource: str = "customer_analytics", access_level: str = "viewer") -> None:
        membership = OrganizationMembership.objects.get(user=user, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource=resource,
            resource_id=None,
            access_level=access_level,
            organization_member=membership,
        )

    def test_viewer_can_list(self):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)
        self.assertEqual(self.client.get(self.endpoint_base).status_code, status.HTTP_200_OK)

    def test_viewer_can_retrieve(self):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)
        response = self.client.get(f"{self.endpoint_base}{self.definition.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_viewer_cannot_create(self):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)
        response = self.client.post(self.endpoint_base, {"name": "New", "display_type": "text"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_update(self):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)
        response = self.client.patch(f"{self.endpoint_base}{self.definition.id}/", {"name": "x"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_delete(self):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)
        response = self.client.delete(f"{self.endpoint_base}{self.definition.id}/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_editor_can_create(self):
        self._set_access_level(self.editor_user, access_level="editor")
        self.client.force_login(self.editor_user)
        response = self.client.post(self.endpoint_base, {"name": "Editor Prop", "display_type": "text"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_editor_can_delete(self):
        self._set_access_level(self.editor_user, access_level="editor")
        self.client.force_login(self.editor_user)
        response = self.client.delete(f"{self.endpoint_base}{self.definition.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_none_access_blocks_list(self):
        self._set_access_level(self.no_access_user, access_level="none")
        self.client.force_login(self.no_access_user)
        self.assertEqual(self.client.get(self.endpoint_base).status_code, status.HTTP_403_FORBIDDEN)

    def test_org_admin_has_full_access(self):
        membership = OrganizationMembership.objects.get(user=self.editor_user, organization=self.organization)
        membership.level = OrganizationMembership.Level.ADMIN
        membership.save()
        self.client.force_login(self.editor_user)
        response = self.client.post(self.endpoint_base, {"name": "Admin Prop", "display_type": "text"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)


class TestCustomPropertyValueViewSet(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.account = create_account(team_id=self.team.id)
        self.text_def = create_custom_property_definition(
            team_id=self.team.id, name="Plan", display_type=DisplayType.TEXT
        )
        self.number_def = create_custom_property_definition(
            team_id=self.team.id, name="Seats", display_type=DisplayType.NUMBER
        )
        self.endpoint = f"/api/projects/{self.team.id}/accounts/{self.account.id}/custom_property_values/"

    def _set(self, definition_id, value, endpoint=None):
        return self.client.post(
            endpoint or self.endpoint, {"definition": str(definition_id), "value": value}, format="json"
        )

    def test_create_value_success(self):
        response = self._set(self.text_def.id, "enterprise")

        self.assertEqual(status.HTTP_201_CREATED, response.status_code, response.json())
        data = response.json()
        self.assertEqual("enterprise", data["value"])
        self.assertEqual(str(self.text_def.id), data["definition_id"])
        self.assertEqual(str(self.account.id), data["account_id"])

    def test_create_numeric_value(self):
        response = self._set(self.number_def.id, 1234.5)

        self.assertEqual(status.HTTP_201_CREATED, response.status_code, response.json())
        self.assertEqual(1234.5, response.json()["value"])

    def test_wrong_type_value_is_rejected(self):
        response = self._set(self.number_def.id, "abc")

        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        self.assertEqual("value", response.json()["attr"])

    def test_unknown_definition_is_rejected(self):
        response = self._set(uuid4(), "x")

        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        self.assertEqual("definition", response.json()["attr"])

    def test_resetting_a_value_supersedes_the_previous_one(self):
        self._set(self.text_def.id, "starter")
        self._set(self.text_def.id, "enterprise")

        values = self.client.get(self.endpoint).json()
        plan_values = [v for v in values if v["definition_id"] == str(self.text_def.id)]
        self.assertEqual(1, len(plan_values))
        self.assertEqual("enterprise", plan_values[0]["value"])

    def test_list_returns_active_values(self):
        self._set(self.text_def.id, "enterprise")
        self._set(self.number_def.id, 42)

        response = self.client.get(self.endpoint)

        self.assertEqual(status.HTTP_200_OK, response.status_code)
        values = {v["definition_id"]: v["value"] for v in response.json()}
        self.assertEqual({str(self.text_def.id): "enterprise", str(self.number_def.id): 42}, values)

    def test_account_from_another_team_returns_404(self):
        other_team = Team.objects.create(organization=self.organization)
        other_account = create_account(team_id=other_team.id)
        endpoint = f"/api/projects/{self.team.id}/accounts/{other_account.id}/custom_property_values/"

        response = self._set(self.text_def.id, "x", endpoint=endpoint)

        self.assertEqual(status.HTTP_404_NOT_FOUND, response.status_code)

    @patch("products.customer_analytics.backend.facade.api.get_accessible_account_id")
    def test_account_deleted_after_access_check_returns_404(self, mock_access):
        # Account passes the access pre-check but is gone by the time the write commits.
        mock_access.return_value = str(uuid4())

        response = self._set(self.text_def.id, "x")

        self.assertEqual(status.HTTP_404_NOT_FOUND, response.status_code)

    def test_unauthenticated_is_rejected(self):
        self.client.logout()

        response = self.client.get(self.endpoint)

        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_source_backed_definition_rejects_manual_write(self):
        saved_query_model = apps.get_model("data_modeling", "DataWarehouseSavedQuery")
        view = saved_query_model.objects.create(team=self.team, name="v", columns={"k": {}, "c": {}})
        CustomPropertySource.objects.unscoped().create(
            team_id=self.team.id,
            definition_id=self.text_def.id,
            saved_query=view,
            source_column="c",
            key_column="k",
        )

        response = self._set(self.text_def.id, "manual")

        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        self.assertEqual("definition", response.json()["attr"])


class TestCustomPropertySourceViewSet(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.endpoint = f"/api/projects/{self.team.id}/custom_property_sources/"
        saved_query_model = apps.get_model("data_modeling", "DataWarehouseSavedQuery")
        self.view = saved_query_model.objects.create(
            team=self.team, name="billing_view", columns={"org_id": {}, "mrr": {}}
        )
        self.definition = create_custom_property_definition(team_id=self.team.id, name="MRR")

    def test_create_list_and_toggle_round_trip(self):
        created = self.client.post(
            self.endpoint,
            {
                "definition": str(self.definition.id),
                "saved_query": str(self.view.id),
                "source_column": "mrr",
                "key_column": "org_id",
            },
            format="json",
        )
        assert created.status_code == status.HTTP_201_CREATED, created.content
        source_id = created.json()["id"]
        assert created.json()["is_enabled"] is True

        listed = self.client.get(self.endpoint)
        assert listed.status_code == status.HTTP_200_OK
        assert [s["id"] for s in listed.json()["results"]] == [source_id]

        toggled = self.client.patch(f"{self.endpoint}{source_id}/", {"is_enabled": False}, format="json")
        assert toggled.status_code == status.HTTP_200_OK
        assert toggled.json()["is_enabled"] is False


class TestAccountNotesViewSet(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.account = Account.objects.unscoped().create(team=self.team, name="Acme Corp")
        self.endpoint_base = f"/api/projects/{self.team.id}/account_notes/"

    def _link_note(self, account: Account | None = None, **kwargs) -> Notebook:
        kwargs.setdefault("visibility", Notebook.Visibility.INTERNAL)
        notebook = Notebook.objects.create(team=self.team, **kwargs)
        ResourceNotebook.objects.create(notebook=notebook, account=account or self.account)
        return notebook

    def test_list_returns_account_notes_with_account_fields(self):
        note = self._link_note(title="Renewal", created_by=self.user)

        response = self.client.get(self.endpoint_base)

        self.assertEqual(status.HTTP_200_OK, response.status_code, response.json())
        results = response.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["short_id"], note.short_id)
        self.assertEqual(results[0]["title"], "Renewal")
        self.assertEqual(results[0]["account_id"], str(self.account.id))
        self.assertEqual(results[0]["account_name"], "Acme Corp")
        self.assertEqual(results[0]["created_by"]["id"], self.user.id)
        self.assertEqual(results[0]["created_by"]["email"], self.user.email)

    def test_list_excludes_unlinked_deleted_noninternal_and_other_team_notes(self):
        included = self._link_note(title="Included")
        Notebook.objects.create(team=self.team, title="Standalone")
        self._link_note(title="Deleted", deleted=True)
        self._link_note(title="Default visibility", visibility=Notebook.Visibility.DEFAULT)
        other_team = Team.objects.create(organization=self.organization)
        other_account = Account.objects.unscoped().create(team=other_team, name="Other")
        other_note = Notebook.objects.create(
            team=other_team, title="Other team", visibility=Notebook.Visibility.INTERNAL
        )
        ResourceNotebook.objects.create(notebook=other_note, account=other_account)

        response = self.client.get(self.endpoint_base)

        short_ids = [n["short_id"] for n in response.json()["results"]]
        self.assertEqual(short_ids, [included.short_id])

    @parameterized.expand(
        [
            ("matches_title", "renewal", {"Renewal planning"}),
            ("matches_content", "pricing", {"Untitled"}),
            ("matches_account_name", "acme", {"Renewal planning", "Untitled", "Kickoff"}),
            ("no_match", "zzzz", set()),
        ]
    )
    def test_list_search(self, _name, search, expected_titles):
        self._link_note(title="Renewal planning", text_content="")
        self._link_note(title="Untitled", text_content="pricing discussion")
        self._link_note(title="Kickoff", text_content="agenda")

        response = self.client.get(f"{self.endpoint_base}?search={search}")

        titles = {n["title"] for n in response.json()["results"]}
        self.assertEqual(titles, expected_titles)

    def test_list_filter_by_account(self):
        other_account = Account.objects.unscoped().create(team=self.team, name="Beta LLC")
        self._link_note(title="Acme note")
        self._link_note(title="Beta note", account=other_account)

        response = self.client.get(f"{self.endpoint_base}?account_id={self.account.id}")

        titles = [n["title"] for n in response.json()["results"]]
        self.assertEqual(titles, ["Acme note"])

    @parameterized.expand(
        [
            ("account_id", "not-a-uuid"),
            ("created_by", "alice"),
            ("created_by", "alice,bob"),
            ("assigned_to", "alice"),
        ]
    )
    def test_list_rejects_malformed_filter(self, param, value):
        response = self.client.get(f"{self.endpoint_base}?{param}={value}")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_filter_by_assigned_to(self):
        # "My accounts" on the Notes tab: notes on accounts where the user is CSM or AE.
        # account_owner is deliberately not treated as "assigned" (mirrors the accounts list).
        csm_account = Account.objects.unscoped().create(
            team=self.team, name="CSM Co", _properties={"csm": {"id": self.user.id, "email": self.user.email}}
        )
        ae_account = Account.objects.unscoped().create(
            team=self.team,
            name="AE Co",
            _properties={"account_executive": {"id": self.user.id, "email": self.user.email}},
        )
        owner_account = Account.objects.unscoped().create(
            team=self.team,
            name="Owner Co",
            _properties={"account_owner": {"id": self.user.id, "email": self.user.email}},
        )
        other_account = Account.objects.unscoped().create(
            team=self.team, name="Other Co", _properties={"csm": {"id": 999999, "email": "someone@x.com"}}
        )
        self._link_note(title="CSM note", account=csm_account)
        self._link_note(title="AE note", account=ae_account)
        self._link_note(title="Owner note", account=owner_account)
        self._link_note(title="Other note", account=other_account)

        response = self.client.get(f"{self.endpoint_base}?assigned_to={self.user.id}")

        titles = {n["title"] for n in response.json()["results"]}
        self.assertEqual(titles, {"CSM note", "AE note"})

    @parameterized.expand(
        [
            ("single", "{uid}"),
            ("comma_joined", "{uid},999999"),  # the encoding the generated frontend client sends
            ("repeated", "{uid}&created_by=999999"),
        ]
    )
    def test_list_filter_by_created_by(self, _name, created_by_query):
        other_user = User.objects.create_and_join(self.organization, "note-author@posthog.com", None)
        self._link_note(title="Mine", created_by=self.user)
        self._link_note(title="Theirs", created_by=other_user)

        query = created_by_query.format(uid=self.user.id)
        response = self.client.get(f"{self.endpoint_base}?created_by={query}")

        titles = [n["title"] for n in response.json()["results"]]
        self.assertEqual(titles, ["Mine"])

    def test_list_orders_by_last_modified_desc_and_paginates(self):
        with freeze_time("2024-01-01"):
            older = self._link_note(title="Older")
        with freeze_time("2024-01-02"):
            newer = self._link_note(title="Newer")

        first_page = self.client.get(f"{self.endpoint_base}?limit=1").json()
        self.assertEqual(first_page["count"], 2)
        self.assertEqual([n["short_id"] for n in first_page["results"]], [newer.short_id])

        second_page = self.client.get(f"{self.endpoint_base}?limit=1&offset=1").json()
        self.assertEqual([n["short_id"] for n in second_page["results"]], [older.short_id])

    def test_list_hides_notes_of_accounts_the_caller_cannot_read(self):
        visible = self._link_note(title="Visible")
        hidden_account = Account.objects.unscoped().create(team=self.team, name="Hidden Inc")
        self._link_note(title="Hidden", account=hidden_account)

        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        viewer = User.objects.create_and_join(self.organization, "notes-viewer@posthog.com", None)
        AccessControl.objects.create(
            team=self.team,
            resource="account",
            resource_id=str(hidden_account.id),
            access_level="none",
            organization_member=OrganizationMembership.objects.get(user=viewer, organization=self.organization),
        )
        self.client.force_login(viewer)

        response = self.client.get(self.endpoint_base)

        self.assertEqual(status.HTTP_200_OK, response.status_code, response.json())
        short_ids = [n["short_id"] for n in response.json()["results"]]
        self.assertEqual(short_ids, [visible.short_id])


class TestAccountRelationshipDefinitionViewSet(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.endpoint_base = f"/api/projects/{self.team.id}/account_relationship_definitions/"

    def _create(self, **overrides):
        payload = {"name": "CSM", "description": "Customer success manager"}
        payload.update(overrides)
        return self.client.post(self.endpoint_base, payload, format="json")

    def test_create_and_list_roundtrip(self):
        response = self._create()

        self.assertEqual(status.HTTP_201_CREATED, response.status_code, response.json())
        data = response.json()
        self.assertEqual(data["name"], "CSM")
        self.assertEqual(data["description"], "Customer success manager")
        self.assertTrue(data["is_single_holder"])

        # nosemgrep: idor-lookup-without-team (test assertion)
        definition = AccountRelationshipDefinition.objects.unscoped().get(id=data["id"])
        self.assertEqual(definition.team, self.team)
        self.assertEqual(definition.created_by, self.user)

        listed = self.client.get(self.endpoint_base)
        self.assertEqual(status.HTTP_200_OK, listed.status_code, listed.json())
        self.assertEqual([d["id"] for d in listed.json()["results"]], [data["id"]])

    def test_create_duplicate_name_returns_conflict(self):
        self._create()
        response = self._create()

        self.assertEqual(status.HTTP_409_CONFLICT, response.status_code, response.json())

    def test_patch_renames_and_toggles_cardinality(self):
        definition_id = self._create(name="FDE").json()["id"]

        response = self.client.patch(
            f"{self.endpoint_base}{definition_id}/",
            {"name": "Field engineer", "is_single_holder": False},
            format="json",
        )

        self.assertEqual(status.HTTP_200_OK, response.status_code, response.json())
        self.assertEqual(response.json()["name"], "Field engineer")
        self.assertFalse(response.json()["is_single_holder"])

    def test_retrieve_returns_definition_and_404_for_unknown(self):
        definition_id = self._create().json()["id"]

        response = self.client.get(f"{self.endpoint_base}{definition_id}/")
        self.assertEqual(status.HTTP_200_OK, response.status_code, response.json())
        self.assertEqual(response.json()["name"], "CSM")

        missing = self.client.get(f"{self.endpoint_base}00000000-0000-0000-0000-000000000000/")
        self.assertEqual(status.HTTP_404_NOT_FOUND, missing.status_code)

    def test_patch_unknown_id_returns_404(self):
        response = self.client.patch(
            f"{self.endpoint_base}00000000-0000-0000-0000-000000000000/", {"name": "X"}, format="json"
        )

        self.assertEqual(status.HTTP_404_NOT_FOUND, response.status_code)

    def test_delete_removes_definition_and_cascades_history(self):
        definition_id = self._create().json()["id"]
        account = create_account(team_id=self.team.id, name="Acme")
        # nosemgrep: idor-lookup-without-team (test setup)
        definition = AccountRelationshipDefinition.objects.unscoped().get(id=definition_id)
        relationships_logic.assign(
            team_id=self.team.id, account=account, definition=definition, user=self.user, created_by=self.user
        )

        response = self.client.delete(f"{self.endpoint_base}{definition_id}/")

        self.assertEqual(status.HTTP_204_NO_CONTENT, response.status_code)
        self.assertFalse(AccountRelationshipDefinition.objects.unscoped().filter(id=definition_id).exists())
        self.assertFalse(AccountRelationship.objects.unscoped().filter(definition_id=definition_id).exists())

    def test_viewer_access_can_list_but_not_write(self):
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        viewer = User.objects.create_and_join(self.organization, "rel-viewer@posthog.com", "testtest")
        AccessControl.objects.create(
            team=self.team,
            resource="customer_analytics",
            resource_id=None,
            access_level="viewer",
            organization_member=OrganizationMembership.objects.get(user=viewer, organization=self.organization),
        )
        self.client.force_login(viewer)

        self.assertEqual(self.client.get(self.endpoint_base).status_code, status.HTTP_200_OK)
        self.assertEqual(self._create().status_code, status.HTTP_403_FORBIDDEN)


class TestAccountRelationshipViewSet(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.account = create_account(team_id=self.team.id)
        self.endpoint = f"/api/projects/{self.team.id}/accounts/{self.account.id}/relationships/"

    def _create_relationship_definition(self, name="CSM"):
        return AccountRelationshipDefinition.objects.for_team(self.team.id).create(
            team_id=self.team.id, name=name, created_by=self.user
        )

    def test_lists_active_relationships_by_default(self):
        csm = self._create_relationship_definition("CSM")
        fde = self._create_relationship_definition("FDE")
        active = relationships_logic.assign(
            team_id=self.team.id, account=self.account, definition=csm, user=self.user, created_by=self.user
        )
        ended = relationships_logic.assign(
            team_id=self.team.id, account=self.account, definition=fde, user=self.user, created_by=self.user
        )
        relationships_logic.end_relationship(
            team_id=self.team.id, account_id=self.account.id, relationship_id=str(ended.id)
        )

        response = self.client.get(self.endpoint)

        self.assertEqual(status.HTTP_200_OK, response.status_code, response.json())
        rows = response.json()
        self.assertEqual([str(active.id)], [row["id"] for row in rows])
        self.assertEqual(rows[0]["definition"]["id"], str(csm.id))
        self.assertEqual(rows[0]["definition"]["name"], "CSM")
        self.assertEqual(rows[0]["user"], {"id": self.user.id, "email": self.user.email})
        self.assertIsNone(rows[0]["ended_at"])

    def test_include_history_returns_full_timeline(self):
        definition = self._create_relationship_definition()
        successor = User.objects.create_and_join(self.organization, "successor@posthog.com", "testtest")
        relationships_logic.assign(
            team_id=self.team.id, account=self.account, definition=definition, user=self.user, created_by=self.user
        )
        relationships_logic.assign(
            team_id=self.team.id, account=self.account, definition=definition, user=successor, created_by=self.user
        )

        response = self.client.get(f"{self.endpoint}?include_history=true")

        self.assertEqual(status.HTTP_200_OK, response.status_code, response.json())
        rows = response.json()
        self.assertEqual(2, len(rows))
        self.assertEqual(rows[0]["user"]["id"], successor.id)
        self.assertIsNone(rows[0]["ended_at"])
        self.assertEqual(rows[1]["user"]["id"], self.user.id)
        self.assertIsNotNone(rows[1]["ended_at"])

    def test_account_from_another_team_returns_404(self):
        other_team = Team.objects.create(organization=self.organization)
        other_account = create_account(team_id=other_team.id)

        response = self.client.get(f"/api/projects/{self.team.id}/accounts/{other_account.id}/relationships/")

        self.assertEqual(status.HTTP_404_NOT_FOUND, response.status_code)

    def test_assign_and_end_roundtrip(self):
        definition = self._create_relationship_definition()

        created = self.client.post(self.endpoint, {"definition": str(definition.id), "user": self.user.id})
        self.assertEqual(status.HTTP_201_CREATED, created.status_code, created.json())
        self.assertEqual(created.json()["definition"]["id"], str(definition.id))
        self.assertEqual(created.json()["user"]["id"], self.user.id)
        self.assertIsNone(created.json()["ended_at"])

        ended = self.client.post(f"{self.endpoint}{created.json()['id']}/end/")
        self.assertEqual(status.HTTP_200_OK, ended.status_code, ended.json())
        self.assertIsNotNone(ended.json()["ended_at"])
        self.assertEqual([], self.client.get(self.endpoint).json())
