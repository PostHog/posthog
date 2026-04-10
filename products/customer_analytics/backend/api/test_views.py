import pytest
from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import Insight
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team
from posthog.models.user import User

from products.customer_analytics.backend.models import CustomerJourney, CustomerProfileConfig


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


@pytest.mark.ee
class TestCustomerAnalyticsAccessControl(APIBaseTest):
    """Resource-level access control tests for customer journeys.

    Note: CustomerProfileConfig is a settings resource and uses project-level
    admin permissions, not resource-level RBAC. See TestCustomerProfileConfigViewSet
    for those tests.
    """

    def setUp(self):
        super().setUp()

        self.organization.available_product_features = [
            {
                "key": AvailableFeature.ADVANCED_PERMISSIONS,
                "name": AvailableFeature.ADVANCED_PERMISSIONS,
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
