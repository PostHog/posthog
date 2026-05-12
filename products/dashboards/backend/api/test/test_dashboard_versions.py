from unittest.mock import patch

from rest_framework import status

from posthog.api.test.dashboards import DashboardAPI
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.test.base import APIBaseTest

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.version_history import (
    RECONSTRUCTABLE_FIELDS,
    apply_dashboard_revert,
    reconstruct_dashboard_at_version,
)


class TestDashboardVersionHistory(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)

    def _get_activity_entries(self, dashboard_id: int) -> list[ActivityLog]:
        return list(
            ActivityLog.objects.filter(
                team_id=self.team.id,
                scope="Dashboard",
                item_id=str(dashboard_id),
            ).order_by("created_at", "id")
        )

    def test_reconstructable_fields_excludes_team_and_relations(self) -> None:
        assert "team" not in RECONSTRUCTABLE_FIELDS
        assert "id" not in RECONSTRUCTABLE_FIELDS
        assert "tiles" not in RECONSTRUCTABLE_FIELDS
        assert "tagged_items" not in RECONSTRUCTABLE_FIELDS
        # Sanity: standard tracked fields are reconstructable
        assert "name" in RECONSTRUCTABLE_FIELDS
        assert "description" in RECONSTRUCTABLE_FIELDS
        assert "filters" in RECONSTRUCTABLE_FIELDS

    def test_versions_endpoint_lists_entries_newest_first(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "v1"})
        self.dashboard_api.update_dashboard(dashboard_id, {"name": "v2"})
        self.dashboard_api.update_dashboard(dashboard_id, {"name": "v3"})

        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/versions/")
        assert response.status_code == status.HTTP_200_OK
        versions = response.json()
        # 1 create + 2 updates
        assert len(versions) == 3
        # Newest first
        assert versions[0]["activity"] == "updated"
        assert versions[-1]["activity"] == "created"
        # User attribution surfaced
        assert versions[0]["user"]["email"] == self.user.email

    def test_versions_endpoint_includes_change_detail(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "original"})
        self.dashboard_api.update_dashboard(dashboard_id, {"name": "renamed"})

        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/versions/")
        assert response.status_code == status.HTTP_200_OK
        latest = response.json()[0]
        changes = (latest["detail"] or {}).get("changes") or []
        name_change = next((c for c in changes if c["field"] == "name"), None)
        assert name_change is not None
        assert name_change["before"] == "original"
        assert name_change["after"] == "renamed"

    def test_reconstruct_returns_current_state_for_latest_entry(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "current"})
        self.dashboard_api.update_dashboard(dashboard_id, {"description": "live"})

        dashboard = Dashboard.objects.get(id=dashboard_id)
        entries = self._get_activity_entries(dashboard_id)
        latest = entries[-1]

        state = reconstruct_dashboard_at_version(dashboard, latest.id, self.team.id)
        assert state["is_current"] is True
        assert state["name"] == "current"
        assert state["description"] == "live"

    def test_reconstruct_walks_back_to_earlier_state(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "v1"})
        self.dashboard_api.update_dashboard(dashboard_id, {"name": "v2", "description": "added desc"})
        self.dashboard_api.update_dashboard(dashboard_id, {"name": "v3"})

        dashboard = Dashboard.objects.get(id=dashboard_id)
        entries = self._get_activity_entries(dashboard_id)
        # entries: [created v1, updated v2, updated v3]
        creation_entry = entries[0]

        state = reconstruct_dashboard_at_version(dashboard, creation_entry.id, self.team.id)
        assert state["is_current"] is False
        assert state["name"] == "v1"
        # Description was added in v2, so reverting to v1 should drop it back to the original ""
        assert state["description"] == ""

    def test_revert_endpoint_restores_dashboard_fields(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "v1"})
        self.dashboard_api.update_dashboard(
            dashboard_id, {"name": "v2", "description": "second", "pinned": True}
        )
        self.dashboard_api.update_dashboard(dashboard_id, {"name": "v3"})

        entries = self._get_activity_entries(dashboard_id)
        # Revert to the "v2" state (entry that introduced description and pinned)
        v2_entry = entries[1]

        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/revert_to_version/",
            {"version_id": str(v2_entry.id)},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        body = response.json()
        assert body["name"] == "v2"
        assert body["description"] == "second"
        assert body["pinned"] is True

        dashboard = Dashboard.objects.get(id=dashboard_id)
        assert dashboard.name == "v2"
        assert dashboard.description == "second"
        assert dashboard.pinned is True

    def test_revert_creates_new_activity_log_entry(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "v1"})
        self.dashboard_api.update_dashboard(dashboard_id, {"name": "v2"})
        entries_before = self._get_activity_entries(dashboard_id)

        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/revert_to_version/",
            {"version_id": str(entries_before[0].id)},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK

        entries_after = self._get_activity_entries(dashboard_id)
        # The revert itself should produce a fresh "updated" entry capturing the diff
        assert len(entries_after) == len(entries_before) + 1
        revert_entry = entries_after[-1]
        assert revert_entry.activity == "updated"
        name_changes = [
            c for c in (revert_entry.detail or {}).get("changes", []) if c.get("field") == "name"
        ]
        assert name_changes and name_changes[0]["after"] == "v1"

    def test_revert_to_unknown_version_returns_404(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "v1"})
        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/revert_to_version/",
            {"version_id": "00000000-0000-0000-0000-000000000000"},
            format="json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_revert_requires_valid_uuid(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "v1"})
        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/revert_to_version/",
            {"version_id": "not-a-uuid"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_revert_does_not_cross_teams(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "v1"})
        self.dashboard_api.update_dashboard(dashboard_id, {"name": "v2"})
        entries = self._get_activity_entries(dashboard_id)

        # Pretend the version_id belongs to another dashboard / team
        other_team = self.organization.teams.create(name="other")
        foreign_entry = ActivityLog.objects.create(
            team_id=other_team.id,
            organization_id=self.organization.id,
            scope="Dashboard",
            item_id=str(dashboard_id),
            activity="updated",
            detail={"changes": []},
        )

        # The revert endpoint runs against `self.team`, so the foreign entry must not be findable
        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/revert_to_version/",
            {"version_id": str(foreign_entry.id)},
            format="json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

        # Sanity: the legitimate entry still works
        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/revert_to_version/",
            {"version_id": str(entries[0].id)},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK

    def test_revert_to_creation_restores_empty_filters_and_default_pinned(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "v1"})
        self.dashboard_api.update_dashboard(
            dashboard_id, {"filters": {"date_from": "-7d"}, "pinned": True}
        )

        entries = self._get_activity_entries(dashboard_id)
        creation_entry = entries[0]

        dashboard = Dashboard.objects.get(id=dashboard_id)
        apply_dashboard_revert(dashboard, creation_entry.id, self.team.id)

        dashboard.refresh_from_db()
        assert dashboard.filters == {}
        assert dashboard.pinned is False

    def test_versions_endpoint_requires_dashboard_edit_permission(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "v1"})

        with patch(
            "posthog.user_permissions.UserDashboardPermissions.can_edit",
            new=False,
        ):
            response = self.client.get(
                f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/versions/"
            )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "edit" in response.json()["detail"].lower()

    def test_versions_endpoint_requires_activity_log_read(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "v1"})

        with patch(
            "posthog.rbac.user_access_control.UserAccessControl.check_access_level_for_resource",
            return_value=False,
        ):
            response = self.client.get(
                f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/versions/"
            )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "access log" in response.json()["detail"].lower()

    def test_revert_endpoint_requires_dashboard_edit_permission(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "v1"})
        self.dashboard_api.update_dashboard(dashboard_id, {"name": "v2"})
        entries = self._get_activity_entries(dashboard_id)

        with patch(
            "posthog.user_permissions.UserDashboardPermissions.can_edit",
            new=False,
        ):
            response = self.client.post(
                f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/revert_to_version/",
                {"version_id": str(entries[0].id)},
                format="json",
            )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_revert_endpoint_requires_activity_log_read(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "v1"})
        self.dashboard_api.update_dashboard(dashboard_id, {"name": "v2"})
        entries = self._get_activity_entries(dashboard_id)

        with patch(
            "posthog.rbac.user_access_control.UserAccessControl.check_access_level_for_resource",
            return_value=False,
        ):
            response = self.client.post(
                f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/revert_to_version/",
                {"version_id": str(entries[0].id)},
                format="json",
            )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "access log" in response.json()["detail"].lower()
