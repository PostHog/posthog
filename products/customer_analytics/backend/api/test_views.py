import pytest
from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.api.tagged_item import set_tags_on_object
from posthog.constants import AvailableFeature
from posthog.models import Insight, Tag, TaggedItem
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team
from posthog.models.user import User

from products.customer_analytics.backend.models import Account, CustomerJourney, CustomerProfileConfig
from products.customer_analytics.backend.models.account import AccountAssignment


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

        journey = CustomerJourney.objects.get(id=data["id"])  # nosemgrep: semgrep.rules.idor-lookup-without-team
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
            CustomerJourney.objects.filter(id=journey_id).exists()  # nosemgrep: semgrep.rules.idor-lookup-without-team
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

        account = Account.objects.unscoped().get(id=data["id"])  # nosemgrep: semgrep.rules.idor-lookup-without-team
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
        from products.notebooks.backend.models import Notebook, ResourceNotebook

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
        from products.notebooks.backend.models import Notebook, ResourceNotebook

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
        from products.notebooks.backend.models import Notebook, ResourceNotebook

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
        from products.notebooks.backend.models import Notebook, ResourceNotebook

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

    def test_retrieve_returns_notebook_for_account(self):
        from products.notebooks.backend.models import Notebook, ResourceNotebook

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
        from products.notebooks.backend.models import Notebook

        unrelated = Notebook.objects.create(
            team=self.team, title="Unrelated", content={}, visibility=Notebook.Visibility.DEFAULT
        )

        response = self.client.get(f"{self.endpoint_base}{unrelated.short_id}/")

        self.assertEqual(status.HTTP_404_NOT_FOUND, response.status_code)

    def test_destroy_notebook_for_account(self):
        from products.notebooks.backend.models import Notebook, ResourceNotebook

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
        from products.notebooks.backend.models import Notebook, ResourceNotebook

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
        from products.notebooks.backend.models import Notebook, ResourceNotebook

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
            from ee.models.rbac.access_control import AccessControl

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
        from ee.models.rbac.access_control import AccessControl

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
