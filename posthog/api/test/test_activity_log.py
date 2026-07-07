from datetime import timedelta
from typing import Any, Optional
from uuid import uuid4

from freezegun import freeze_time
from freezegun.api import FrozenDateTimeFactory, StepTickTimeFactory, TickingDateTimeFactory
from posthog.test.base import APIBaseTest, QueryMatchingTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.models.activity_logging.activity_log import Detail, log_activity


def _feature_flag_json_payload(key: str) -> dict:
    return {
        "key": key,
        "name": "",
        "filters": {
            "groups": [{"properties": [], "rollout_percentage": None}],
            "multivariate": None,
        },
        "deleted": False,
        "active": True,
        "created_by": None,
        "ensure_experience_continuity": False,
        "experiment_set": None,
    }


class TestActivityLog(APIBaseTest, QueryMatchingTest):
    def setUp(self) -> None:
        super().setUp()
        self.other_user = User.objects.create_and_join(
            organization=self.organization,
            email="other_user@posthog.com",
            password="",
        )
        self.third_user = User.objects.create_and_join(
            organization=self.organization,
            email="third_user@posthog.com",
            password="",
        )

        # user one has created 10 insights and 2 flags
        # user two has edited them all
        # user three has edited most of them after that
        self._create_and_edit_things()

        self.client.force_login(self.user)

    def tearDown(self):
        super().tearDown()
        self.client.force_login(self.user)

    def _create_insight(
        self,
        data: dict[str, Any],
        team_id: Optional[int] = None,
        expected_status: int = status.HTTP_201_CREATED,
    ) -> tuple[int, dict[str, Any]]:
        if team_id is None:
            team_id = self.team.id

        if "filters" not in data:
            data["filters"] = {"events": [{"id": "$pageview"}]}

        response = self.client.post(f"/api/projects/{team_id}/insights", data=data)
        self.assertEqual(response.status_code, expected_status)

        response_json = response.json()
        return response_json.get("id", None), response_json

    def _create_and_edit_things(self):
        with freeze_time("2023-08-17") as frozen_time:
            # almost every change below will be more than 5 minutes apart
            created_insights = []
            for _ in range(0, 11):
                frozen_time.tick(delta=timedelta(minutes=6))
                insight_id, _ = self._create_insight({})
                created_insights.append(insight_id)

            frozen_time.tick(delta=timedelta(minutes=6))
            flag_one = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags/",
                _feature_flag_json_payload("one"),
            ).json()["id"]

            frozen_time.tick(delta=timedelta(minutes=6))
            flag_two = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags/",
                _feature_flag_json_payload("two"),
            ).json()["id"]

            frozen_time.tick(delta=timedelta(minutes=6))

            notebook_json = self.client.post(
                f"/api/projects/{self.team.id}/notebooks/",
                {"content": "print('hello world')", "name": "notebook"},
            ).json()

            # other user now edits them
            notebook_version = self._edit_them_all(
                created_insights,
                flag_one,
                flag_two,
                notebook_json["short_id"],
                notebook_json["version"],
                self.other_user,
                frozen_time,
            )
            # third user edits them
            self._edit_them_all(
                created_insights,
                flag_one,
                flag_two,
                notebook_json["short_id"],
                notebook_version,
                self.third_user,
                frozen_time,
            )

    def _edit_them_all(
        self,
        created_insights: list[int],
        flag_one: str,
        flag_two: str,
        notebook_short_id: str,
        notebook_version: int,
        the_user: User,
        frozen_time: FrozenDateTimeFactory | StepTickTimeFactory | TickingDateTimeFactory,
    ) -> int:
        self.client.force_login(the_user)
        for created_insight_id in created_insights[:7]:
            frozen_time.tick(delta=timedelta(minutes=6))
            update_response = self.client.patch(
                f"/api/projects/{self.team.id}/insights/{created_insight_id}",
                {"name": f"{created_insight_id}-insight-changed-by-{the_user.id}"},
            )
            self.assertEqual(update_response.status_code, status.HTTP_200_OK)

            frozen_time.tick(delta=timedelta(minutes=6))
        assert (
            self.client.patch(
                f"/api/projects/{self.team.id}/feature_flags/{flag_one}",
                {"name": f"one-edited-by-{the_user.id}"},
            ).status_code
            == status.HTTP_200_OK
        )

        frozen_time.tick(delta=timedelta(minutes=6))
        assert (
            self.client.patch(
                f"/api/projects/{self.team.id}/feature_flags/{flag_two}",
                {"name": f"two-edited-by-{the_user.id}"},
            ).status_code
            == status.HTTP_200_OK
        )

        frozen_time.tick(delta=timedelta(minutes=6))
        # notebooks save while you're typing so, we get multiple activities per edit
        for typed_text in [
            "print",
            "print(",
            "print('hello world again')",
            "print('hello world again from ",
            f"print('hello world again from {the_user.id}')",
        ]:
            frozen_time.tick(delta=timedelta(seconds=5))
            assert (
                self.client.patch(
                    f"/api/projects/{self.team.id}/notebooks/{notebook_short_id}",
                    {"content": typed_text, "version": notebook_version},
                ).status_code
                == status.HTTP_200_OK
            )
            notebook_version = notebook_version + 1

        return notebook_version

    def test_can_list_all_activity(self) -> None:
        # Enable org-level activity logs to include org-scoped records
        self.team.receive_org_level_activity_logs = True
        self.team.save()

        res = self.client.get(f"/api/projects/{self.team.id}/activity_log")

        assert res.status_code == status.HTTP_200_OK
        assert len(res.json()["results"]) == 46

    def test_can_list_all_activity_filtered_by_scope(self) -> None:
        res = self.client.get(f"/api/projects/{self.team.id}/activity_log?scope=FeatureFlag")
        assert res.status_code == status.HTTP_200_OK
        assert len(res.json()["results"]) == 6
        assert [r["scope"] for r in res.json()["results"]] == ["FeatureFlag"] * 6


class TestActivityLogAuditLogsGate(APIBaseTest):
    @parameterized.expand([("activity_log",), ("advanced_activity_logs",)])
    def test_endpoint_blocked_on_cloud_without_audit_logs_feature(self, endpoint: str) -> None:
        self.organization.available_product_features = []
        self.organization.save()

        with self.is_cloud(True):
            res = self.client.get(f"/api/projects/{self.team.id}/{endpoint}/")

        assert res.status_code == status.HTTP_402_PAYMENT_REQUIRED

    @parameterized.expand([("activity_log",), ("advanced_activity_logs",)])
    def test_endpoint_allowed_on_cloud_with_audit_logs_feature(self, endpoint: str) -> None:
        self.organization.available_product_features = [{"key": AvailableFeature.AUDIT_LOGS, "name": "Activity logs"}]
        self.organization.save()

        with self.is_cloud(True):
            res = self.client.get(f"/api/projects/{self.team.id}/{endpoint}/")

        assert res.status_code == status.HTTP_200_OK

    @parameterized.expand([("activity_log",), ("advanced_activity_logs",)])
    def test_endpoint_allowed_on_self_hosted_without_audit_logs_feature(self, endpoint: str) -> None:
        self.organization.available_product_features = []
        self.organization.save()

        with self.is_cloud(False):
            res = self.client.get(f"/api/projects/{self.team.id}/{endpoint}/")

        assert res.status_code == status.HTTP_200_OK

    @parameterized.expand([("activity_log",), ("advanced_activity_logs",)])
    def test_endpoint_allowed_for_impersonator_without_audit_logs_feature(self, endpoint: str) -> None:
        self.organization.available_product_features = []
        self.organization.save()

        with self.is_cloud(True), patch("posthog.permissions.is_impersonated_session", return_value=True):
            res = self.client.get(f"/api/projects/{self.team.id}/{endpoint}/")

        assert res.status_code == status.HTTP_200_OK


class TestOrganizationAdvancedActivityLogsViewSet(APIBaseTest):
    """Tests for the org-scoped activity logs viewset at /api/organizations/<id>/advanced_activity_logs/."""

    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = False
        self.user.save()
        # Promote the seeded user to admin for the happy-path tests; downgrade per-test as needed.
        OrganizationMembership.objects.filter(user=self.user, organization=self.organization).update(
            level=OrganizationMembership.Level.ADMIN
        )
        # Audit logs feature must be unlocked for the org so the cloud paywall doesn't pre-empt the
        # access-control checks under test.
        self.organization.available_product_features = [{"key": AvailableFeature.AUDIT_LOGS, "name": "Activity logs"}]
        self.organization.save()

        self.other_team_in_org = Team.objects.create(organization=self.organization, name="Other team in org")

        self.outside_organization = Organization.objects.create(name="Outside org")
        self.outside_team = Team.objects.create(organization=self.outside_organization, name="Outside team")

        self._seed_activity_rows()

    def _seed_activity_rows(self) -> None:
        # Project-scoped row in primary team (both team_id and organization_id populated)
        log_activity(
            organization_id=self.organization.id,
            team_id=self.team.id,
            user=self.user,
            was_impersonated=False,
            item_id="flag-1",
            scope="FeatureFlag",
            activity="created",
            detail=Detail(name="seed"),
            force_save=True,
        )
        # Project-scoped row in the second team of the same org
        log_activity(
            organization_id=self.organization.id,
            team_id=self.other_team_in_org.id,
            user=self.user,
            was_impersonated=False,
            item_id="insight-1",
            scope="Insight",
            activity="created",
            detail=Detail(name="seed"),
            force_save=True,
        )
        # Org-scoped row (team_id is null)
        log_activity(
            organization_id=self.organization.id,
            team_id=None,
            user=self.user,
            was_impersonated=False,
            item_id=str(uuid4()),
            scope="Organization",
            activity="updated",
            detail=Detail(name="seed"),
            force_save=True,
        )
        # Row in a completely different organization — must NOT be visible
        log_activity(
            organization_id=self.outside_organization.id,
            team_id=self.outside_team.id,
            user=self.user,
            was_impersonated=False,
            item_id="flag-outside",
            scope="FeatureFlag",
            activity="created",
            detail=Detail(name="seed"),
            force_save=True,
        )

    def _list(self, **query) -> Any:
        url = f"/api/organizations/{self.organization.id}/advanced_activity_logs/"
        return self.client.get(url, data=query)

    def test_admin_sees_all_org_rows(self) -> None:
        # Spot-check that the endpoint returns org-wide content (not just an empty 200)
        # when the requester is allowed in. Permission gating itself is covered below.
        res = self._list()

        assert res.status_code == status.HTTP_200_OK
        results = res.json()["results"]
        item_ids = {row["item_id"] for row in results}
        assert "flag-1" in item_ids
        assert "insight-1" in item_ids
        # Org-scoped row appears
        assert any(row["scope"] == "Organization" for row in results)
        # Cross-org row does NOT appear
        assert "flag-outside" not in item_ids

    def test_invalid_filter_is_rejected(self) -> None:
        # Wiring guard: the viewset must run AdvancedActivityLogFiltersSerializer on the query params.
        # The exhaustive filter-shape matrix is unit-tested without a DB in
        # TestAdvancedActivityLogFiltersSerializerValidation (advanced_activity_logs/test_filters.py).
        res = self._list(ip_addresses="not-an-ip")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    @parameterized.expand(
        [
            ("owner", OrganizationMembership.Level.OWNER, status.HTTP_200_OK),
            ("admin", OrganizationMembership.Level.ADMIN, status.HTTP_200_OK),
            ("member", OrganizationMembership.Level.MEMBER, status.HTTP_403_FORBIDDEN),
            ("non_member", None, status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_access_control_by_membership_level(self, _name: str, level: Optional[int], expected_status: int) -> None:
        if level is None:
            outsider = User.objects.create_and_join(
                organization=self.outside_organization, email="outsider@example.com", password=""
            )
            self.client.force_login(outsider)
        else:
            OrganizationMembership.objects.filter(user=self.user, organization=self.organization).update(level=level)

        res = self._list()

        assert res.status_code == expected_status

    def test_team_ids_filter_narrows_to_selected_projects(self) -> None:
        res = self._list(team_ids=self.team.id)

        assert res.status_code == status.HTTP_200_OK
        item_ids = {row["item_id"] for row in res.json()["results"]}
        assert item_ids == {"flag-1"}

    def test_audit_logs_feature_required_on_cloud(self) -> None:
        self.organization.available_product_features = []
        self.organization.save()

        with self.is_cloud(True):
            res = self._list()

        assert res.status_code == status.HTTP_402_PAYMENT_REQUIRED

    def test_export_endpoint_is_disabled_on_organization_route(self) -> None:
        url = f"/api/organizations/{self.organization.id}/advanced_activity_logs/export/"
        res = self.client.post(url, data={"format": "csv"}, format="json")

        assert res.status_code == status.HTTP_400_BAD_REQUEST


class TestOrganizationAdvancedActivityLogsAvailableFilters(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        OrganizationMembership.objects.filter(user=self.user, organization=self.organization).update(
            level=OrganizationMembership.Level.ADMIN
        )
        self.organization.available_product_features = [{"key": AvailableFeature.AUDIT_LOGS, "name": "Activity logs"}]
        self.organization.save()

        self.other_team = Team.objects.create(organization=self.organization, name="Other team")
        log_activity(
            organization_id=self.organization.id,
            team_id=self.team.id,
            user=self.user,
            was_impersonated=False,
            item_id="flag-1",
            scope="FeatureFlag",
            activity="created",
            detail=Detail(name="seed"),
            force_save=True,
        )
        log_activity(
            organization_id=self.organization.id,
            team_id=self.other_team.id,
            user=self.user,
            was_impersonated=False,
            item_id="insight-1",
            scope="Insight",
            activity="updated",
            detail=Detail(name="seed"),
            force_save=True,
        )

    def test_available_filters_returns_org_wide_static_filters(self) -> None:
        # Small-org branch (live computation path) — covered by default in tests.
        url = f"/api/organizations/{self.organization.id}/advanced_activity_logs/available_filters/"
        res = self.client.get(url)

        assert res.status_code == status.HTTP_200_OK
        body = res.json()
        scopes = {entry["value"] for entry in body["static_filters"]["scopes"]}
        # Both project-level scopes appear because the queryset is org-wide
        assert {"FeatureFlag", "Insight"}.issubset(scopes)
        activities = {entry["value"] for entry in body["static_filters"]["activities"]}
        assert {"created", "updated"}.issubset(activities)
