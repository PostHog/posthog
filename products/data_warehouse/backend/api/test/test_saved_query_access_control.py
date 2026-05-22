import pytest

from parameterized import parameterized
from rest_framework import status

from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

from products.data_warehouse.backend.api.test._access_control_base import WarehouseAccessControlTestMixin
from products.data_warehouse.backend.models import DataWarehouseSavedQuery, DataWarehouseSavedQueryFolder

try:
    from ee.models.rbac.access_control import AccessControl
except ImportError:
    pass


@pytest.mark.ee
class TestDataWarehouseSavedQueryAccessControl(WarehouseAccessControlTestMixin):
    # Resource-level AC uses warehouse_table (views inherit from tables).
    # Object-level AC on a specific saved query still keys on "warehouse_view"
    # because model_to_resource(DataWarehouseSavedQuery) == "warehouse_view".
    resource = "warehouse_objects"

    def setUp(self):
        super().setUp()
        self.saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="my_view",
            query={"kind": "HogQLQuery", "query": "select 1"},
            created_by=self.user,
        )

    def _list_url(self) -> str:
        return f"/api/environments/{self.team.pk}/warehouse_saved_queries/"

    def _detail_url(self) -> str:
        return f"/api/environments/{self.team.pk}/warehouse_saved_queries/{self.saved_query.id}/"

    @parameterized.expand(
        [
            # (access_level, method, expected_status, patch_body)
            ("viewer", "GET", status.HTTP_200_OK, None),
            ("viewer", "PATCH", status.HTTP_403_FORBIDDEN, {"name": "updated"}),
            ("viewer", "DELETE", status.HTTP_403_FORBIDDEN, None),
            ("editor", "GET", status.HTTP_200_OK, None),
            ("editor", "PATCH", status.HTTP_200_OK, {"name": "updated_name"}),
            ("none", "GET", status.HTTP_403_FORBIDDEN, None),
        ]
    )
    def test_access_level_matrix(self, access_level, method, expected_status, patch_body):
        user = (
            self.viewer_user
            if access_level == "viewer"
            else self.editor_user
            if access_level == "editor"
            else self.no_access_user
        )
        self._create_access_control(user, access_level=access_level)
        self.client.force_login(user)

        if method == "GET":
            response = self.client.get(self._detail_url())
        elif method == "PATCH":
            response = self.client.patch(self._detail_url(), data=patch_body)
        elif method == "DELETE":
            response = self.client.delete(self._detail_url())
        else:
            raise AssertionError(f"Unsupported method {method}")

        self.assertEqual(response.status_code, expected_status)

    def test_viewer_can_list(self):
        self._create_access_control(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)
        self.assertEqual(self.client.get(self._list_url()).status_code, status.HTTP_200_OK)

    def test_project_default_none_blocks_non_creator_retrieve(self):
        self._create_project_default(access_level="none")
        self.client.force_login(self.viewer_user)
        self.assertEqual(self.client.get(self._detail_url()).status_code, status.HTTP_403_FORBIDDEN)

    def test_creator_list_filters_to_own_queries_when_explicit_viewer(self):
        # Creator sees their own query; an object-level 'none' on another user's query excludes it.
        other_user = User.objects.create_and_join(self.organization, "otheruser@posthog.com", "testtest")
        other_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="other_view",
            query={"kind": "HogQLQuery", "query": "select 1"},
            created_by=other_user,
        )
        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        # Object-level AC for saved queries uses "warehouse_view" (the model's own resource).
        AccessControl.objects.create(
            team=self.team,
            resource="warehouse_view",
            resource_id=str(other_query.id),
            access_level="none",
            organization_member=membership,
        )
        self.client.force_login(self.user)
        response = self.client.get(self._list_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [q["id"] for q in response.json()["results"]]
        self.assertIn(str(self.saved_query.id), ids)
        self.assertNotIn(str(other_query.id), ids)

    def test_non_creator_list_blocked_with_project_default_none(self):
        self._create_project_default(access_level="none")
        self.client.force_login(self.viewer_user)
        self.assertEqual(self.client.get(self._list_url()).status_code, status.HTTP_403_FORBIDDEN)

    def test_explicit_viewer_access_allows_list_with_project_default_none(self):
        self._create_project_default(access_level="none")
        self._create_access_control(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)
        self.assertEqual(self.client.get(self._list_url()).status_code, status.HTTP_200_OK)

    def test_object_level_access_blocks_specific_query(self):
        # Grant viewer at resource level (warehouse_table), then deny object-level on this specific view.
        self._create_access_control(self.viewer_user, access_level="viewer")
        self._create_access_control(
            self.viewer_user, resource="warehouse_view", resource_id=str(self.saved_query.id), access_level="none"
        )
        self.client.force_login(self.viewer_user)
        self.assertEqual(self.client.get(self._detail_url()).status_code, status.HTTP_403_FORBIDDEN)

    def test_user_access_level_field_is_present_in_response(self):
        self._create_access_control(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)
        response = self.client.get(self._detail_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json().get("user_access_level"), "viewer")

    def test_upsert_create_respects_object_level_none(self):
        # Regression: POST with an existing query's name performs an UPSERT-update.
        # Object-level access controls must still apply even though get_object() isn't called.
        self._create_access_control(self.editor_user, access_level="editor")  # resource-level editor
        self._create_access_control(
            self.editor_user, resource="warehouse_view", resource_id=str(self.saved_query.id), access_level="none"
        )  # but object-level none for this specific view
        self.client.force_login(self.editor_user)
        response = self.client.post(
            self._list_url(),
            data={"name": self.saved_query.name, "query": {"kind": "HogQLQuery", "query": "select 2"}},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        # Confirm the query was NOT overwritten
        self.saved_query.refresh_from_db()
        self.assertEqual(self.saved_query.query, {"kind": "HogQLQuery", "query": "select 1"})

    def test_resource_level_row_on_child_alone_has_no_effect(self):
        # Contract: warehouse_view inherits from warehouse_objects, so resource-level rows
        # keyed on warehouse_view (without resource_id) are intentionally bypassed — only
        # the umbrella warehouse_objects scope counts. The distinguishing assertion is that
        # creator bypass (resolved via access_level_for_object) still returns "manager" on
        # the user's own query, even with a child-only `none` row that would otherwise
        # short-circuit resource access. If has_access_levels_for_resource ever started
        # honoring child rows it would route through access_level_for_resource and lose
        # creator bypass, returning the default ("editor") instead.
        own_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="own_view",
            query={"kind": "HogQLQuery", "query": "select 1"},
            created_by=self.viewer_user,
        )
        AccessControl.objects.create(team=self.team, resource="warehouse_view", access_level="none")
        self.client.force_login(self.viewer_user)

        url = f"/api/environments/{self.team.pk}/warehouse_saved_queries/{own_query.id}/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Creator bypass: highest level for warehouse_view is "manager".
        self.assertEqual(response.json().get("user_access_level"), "manager")

    def test_object_level_access_grants_through_resource_default_none(self):
        # When the project default is 'none' (no resource access), an object-level grant on a
        # specific saved query still lets the user retrieve and edit that query, while other
        # queries remain blocked. This relies on AccessControlPermission falling back to
        # has_any_specific_access_for_resource.
        other_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="other_view",
            query={"kind": "HogQLQuery", "query": "select 1"},
            created_by=self.user,
        )
        self._create_project_default(access_level="none")
        # Grant editor on this specific saved query (object-level row keyed on warehouse_view).
        self._create_access_control(
            self.viewer_user,
            resource="warehouse_view",
            resource_id=str(self.saved_query.id),
            access_level="editor",
        )
        self.client.force_login(self.viewer_user)

        # The granted query is retrievable and editable.
        self.assertEqual(self.client.get(self._detail_url()).status_code, status.HTTP_200_OK)
        patch_response = self.client.patch(
            self._detail_url(), data={"name": "renamed_via_object_grant"}, content_type="application/json"
        )
        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)

        # A different query without an object-level grant stays blocked.
        other_url = f"/api/environments/{self.team.pk}/warehouse_saved_queries/{other_query.id}/"
        self.assertEqual(self.client.get(other_url).status_code, status.HTTP_403_FORBIDDEN)


@pytest.mark.ee
class TestDataWarehouseSavedQueryFolderAccessControl(WarehouseAccessControlTestMixin):
    # Folder resource-level AC goes through warehouse_table via inheritance.
    # Object-level AC on specific folders still keys on "warehouse_view".
    resource = "warehouse_objects"

    def setUp(self):
        super().setUp()
        self.folder = DataWarehouseSavedQueryFolder.objects.create(
            team=self.team, name="Marketing", created_by=self.user
        )

    def _list_url(self) -> str:
        return f"/api/environments/{self.team.pk}/warehouse_saved_query_folders/"

    def _detail_url(self) -> str:
        return f"/api/environments/{self.team.pk}/warehouse_saved_query_folders/{self.folder.id}/"

    def test_folder_list_works_without_restrictions(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self._list_url()).status_code, status.HTTP_200_OK)

    def test_folder_retrieve_respects_warehouse_view_default(self):
        self._create_project_default(access_level="none")
        self.client.force_login(self.viewer_user)
        self.assertEqual(self.client.get(self._detail_url()).status_code, status.HTTP_403_FORBIDDEN)

    def test_folder_viewer_can_retrieve(self):
        self._create_access_control(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)
        response = self.client.get(self._detail_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_folder_viewer_cannot_update(self):
        self._create_access_control(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)
        response = self.client.patch(self._detail_url(), data={"name": "renamed"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_folder_user_access_level_field_is_present(self):
        self._create_access_control(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)
        response = self.client.get(self._detail_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json().get("user_access_level"), "viewer")

    def test_folder_object_level_none_blocks_specific_folder(self):
        self._create_access_control(self.viewer_user, access_level="viewer")
        self._create_access_control(
            self.viewer_user, resource="warehouse_view", resource_id=str(self.folder.id), access_level="none"
        )
        self.client.force_login(self.viewer_user)
        self.assertEqual(self.client.get(self._detail_url()).status_code, status.HTTP_403_FORBIDDEN)

    def test_folder_creator_list_filters_out_blocked_other_folder(self):
        # Creator has resource access, but an object-level 'none' on another user's folder excludes it from their list.
        # Creator bypass applies at the queryset filter layer, not at has_permission — so the creator needs
        # at least resource-level access for the list endpoint to return 200.
        other_user = User.objects.create_and_join(self.organization, "otheruser@posthog.com", "testtest")
        other_folder = DataWarehouseSavedQueryFolder.objects.create(team=self.team, name="Other", created_by=other_user)
        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        # Object-level AC on folders uses "warehouse_view" (the model's own resource).
        AccessControl.objects.create(
            team=self.team,
            resource="warehouse_view",
            resource_id=str(other_folder.id),
            access_level="none",
            organization_member=membership,
        )
        self.client.force_login(self.user)
        response = self.client.get(self._list_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Folder endpoint is unpaginated - response is a flat list of folder dicts
        ids = [f["id"] for f in response.json()]
        self.assertIn(str(self.folder.id), ids)
        self.assertNotIn(str(other_folder.id), ids)
