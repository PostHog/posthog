import uuid
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationMembership, Project, Team, User

from products.access_control.backend.models.access_control import AccessControl
from products.ai_observability.backend.models.taggers import Tagger


def _setup_team():
    org = Organization.objects.create(name="test")
    project = Project.objects.create(id=Team.objects.increment_id_sequence(), organization=org)
    team = Team.objects.create(
        id=project.id,
        project=project,
        organization=org,
        api_token=str(uuid4()),
        test_account_filters=[
            {
                "key": "email",
                "value": "@posthog.com",
                "operator": "not_icontains",
                "type": "person",
            }
        ],
        has_completed_onboarding_for={"product_analytics": True},
    )
    User.objects.create_and_join(org, "test-taggers@posthog.com", "testpassword123")
    return team


def _make_tagger_config(**overrides):
    defaults = {
        "prompt": "Which product features were discussed?",
        "tags": [
            {"name": "billing", "description": "Billing related"},
            {"name": "analytics", "description": "Analytics related"},
        ],
        "min_tags": 0,
        "max_tags": 2,
    }
    return {**defaults, **overrides}


class TestTaggersApi(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        feature_flag_patch = patch(
            "posthog.permissions.posthog_feature_flag_enabled",
            return_value=True,
        )
        feature_flag_patch.start()
        self.addCleanup(feature_flag_patch.stop)

    def _create_tagger(self) -> Tagger:
        return Tagger.objects.create(
            name="Feature Tagger", tagger_config=_make_tagger_config(), team=self.team, created_by=self.user
        )

    def test_feature_flag_gates_the_api_server_side(self):
        with patch("posthog.permissions.posthog_feature_flag_enabled", return_value=False):
            response = self.client.get(f"/api/environments/{self.team.id}/taggers/")

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_unauthenticated_user_cannot_access_taggers(self):
        self.client.logout()
        response = self.client.get(f"/api/environments/{self.team.id}/taggers/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @parameterized.expand(
        [
            ("create", "post", False),
            ("update", "put", True),
            ("partial_update", "patch", True),
            ("delete", "delete", True),
        ]
    )
    def test_writes_are_not_allowed(self, _name: str, method: str, on_detail: bool):
        tagger = self._create_tagger()
        url = f"/api/environments/{self.team.id}/taggers/" + (f"{tagger.id}/" if on_detail else "")

        response = getattr(self.client, method)(
            url, {"name": "Renamed", "enabled": True, "tagger_config": _make_tagger_config()}, format="json"
        )

        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        assert list(Tagger.objects.values_list("name", "enabled", "deleted")) == [("Feature Tagger", False, False)]

    def test_can_retrieve_list_of_taggers(self):
        Tagger.objects.create(
            name="Tagger 1",
            tagger_config=_make_tagger_config(),
            team=self.team,
            created_by=self.user,
        )
        Tagger.objects.create(
            name="Tagger 2",
            tagger_config=_make_tagger_config(),
            team=self.team,
            created_by=self.user,
        )
        Tagger.objects.create(
            name="Deleted tagger",
            tagger_config=_make_tagger_config(),
            team=self.team,
            created_by=self.user,
            deleted=True,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/taggers/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 2

        names = [t["name"] for t in response.data["results"]]
        assert "Tagger 1" in names
        assert "Tagger 2" in names

    @parameterized.expand(
        [
            ("default", None, "-created_at"),
            ("created_at_ascending", "created_at", "created_at"),
        ]
    )
    def test_list_pages_are_stable_when_taggers_share_a_created_at(
        self, _name: str, order_by: str | None, expected_order: str
    ) -> None:
        for index in range(5):
            Tagger.objects.create(
                name=f"Tagger {index}",
                tagger_config=_make_tagger_config(),
                team=self.team,
                created_by=self.user,
            )
        Tagger.objects.filter(team=self.team).update(created_at="2026-01-01T00:00:00Z")

        paged_ids = []
        for offset in range(5):
            query = {"limit": "1", "offset": str(offset)}
            if order_by is not None:
                query["order_by"] = order_by
            response = self.client.get(f"/api/environments/{self.team.id}/taggers/", query)
            assert response.status_code == status.HTTP_200_OK
            paged_ids.append(response.data["results"][0]["id"])

        expected_ids = [
            str(tagger_id)
            for tagger_id in Tagger.objects.filter(team=self.team)
            .order_by(expected_order, "id")
            .values_list("id", flat=True)
        ]
        assert paged_ids == expected_ids

    def test_can_get_single_tagger(self):
        tagger = Tagger.objects.create(
            name="Test Tagger",
            description="Test desc",
            enabled=True,
            tagger_config=_make_tagger_config(),
            conditions=[{"id": "test", "rollout_percentage": 100, "properties": []}],
            team=self.team,
            created_by=self.user,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/taggers/{tagger.id}/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["name"] == "Test Tagger"
        assert response.data["description"] == "Test desc"
        assert response.data["enabled"] is True
        assert response.data["tagger_config"]["prompt"] == "Which product features were discussed?"

    def test_can_search_taggers(self):
        Tagger.objects.create(
            name="Feature Tagger",
            description="Tags features",
            tagger_config=_make_tagger_config(),
            team=self.team,
            created_by=self.user,
        )
        Tagger.objects.create(
            name="Intent Classifier",
            description="Classifies intent",
            tagger_config=_make_tagger_config(),
            team=self.team,
            created_by=self.user,
        )

        # Search by name
        response = self.client.get(f"/api/environments/{self.team.id}/taggers/?search=feature")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["name"] == "Feature Tagger"

        # Search by description
        response = self.client.get(f"/api/environments/{self.team.id}/taggers/?search=intent")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["name"] == "Intent Classifier"

    def test_can_filter_by_enabled_status(self):
        Tagger.objects.create(
            name="Enabled Tagger",
            tagger_config=_make_tagger_config(),
            enabled=True,
            team=self.team,
            created_by=self.user,
        )
        Tagger.objects.create(
            name="Disabled Tagger",
            tagger_config=_make_tagger_config(),
            enabled=False,
            team=self.team,
            created_by=self.user,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/taggers/?enabled=true")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["name"] == "Enabled Tagger"

        response = self.client.get(f"/api/environments/{self.team.id}/taggers/?enabled=false")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["name"] == "Disabled Tagger"

    def test_can_find_the_tagger_an_evaluation_replaced(self):
        evaluation_id = uuid.uuid4()
        for name, migrated_to in (("Kept", None), ("Moved", evaluation_id), ("Moved elsewhere", uuid.uuid4())):
            Tagger.objects.create(
                name=name,
                tagger_config=_make_tagger_config(),
                team=self.team,
                migrated_to_evaluation_id=migrated_to,
            )

        response = self.client.get(
            f"/api/environments/{self.team.id}/taggers/?migrated_to_evaluation_id={evaluation_id}"
        )

        assert response.status_code == status.HTTP_200_OK
        assert [(row["name"], row["migrated_to_evaluation_id"]) for row in response.data["results"]] == [
            ("Moved", str(evaluation_id))
        ]

    def test_cannot_access_other_teams_taggers(self):
        other_team = _setup_team()

        other_tagger = Tagger.objects.create(
            name="Other Team Tagger",
            tagger_config=_make_tagger_config(),
            team=other_team,
            created_by=self.user,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/taggers/{other_tagger.id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

        response = self.client.get(f"/api/environments/{self.team.id}/taggers/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 0


class TestTaggersAccessControl(APIBaseTest):
    # Tagger has its own access control resource (see ACCESS_CONTROL_RESOURCES in
    # products/access_control/backend/facade/user_access_control.py), independent of the `llm_analytics` resource
    # that Evaluations and Datasets inherit from.
    def setUp(self) -> None:
        super().setUp()
        feature_flag_patch = patch(
            "posthog.permissions.posthog_feature_flag_enabled",
            return_value=True,
        )
        feature_flag_patch.start()
        self.addCleanup(feature_flag_patch.stop)
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()

        self.viewer_user = User.objects.create_and_join(self.organization, "tagger-viewer@posthog.com", "testtest")
        self.no_access_user = User.objects.create_and_join(self.organization, "tagger-noaccess@posthog.com", "testtest")

        self._grant_tagger_access(self.viewer_user, "viewer")
        self._grant_tagger_access(self.no_access_user, "none")

    def _grant_tagger_access(self, user: User, access_level: str) -> AccessControl:
        membership = OrganizationMembership.objects.get(user=user, organization=self.organization)
        return AccessControl.objects.create(
            team=self.team,
            resource="tagger",
            resource_id=None,
            access_level=access_level,
            organization_member=membership,
        )

    def test_no_access_user_cannot_list_taggers(self):
        self.client.force_login(self.no_access_user)

        list_response = self.client.get(f"/api/environments/{self.team.id}/taggers/")
        assert list_response.status_code == status.HTTP_403_FORBIDDEN

    def test_viewer_user_can_read_taggers(self):
        tagger = Tagger.objects.create(
            name="Existing Tagger",
            tagger_config=_make_tagger_config(),
            team=self.team,
            created_by=self.user,
        )
        self.client.force_login(self.viewer_user)

        list_response = self.client.get(f"/api/environments/{self.team.id}/taggers/")
        assert list_response.status_code == status.HTTP_200_OK
        assert len(list_response.data["results"]) == 1

        retrieve_response = self.client.get(f"/api/environments/{self.team.id}/taggers/{tagger.id}/")
        assert retrieve_response.status_code == status.HTTP_200_OK
