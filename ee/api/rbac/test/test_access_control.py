import json
from unittest.mock import MagicMock, patch
from rest_framework import status

from ee.api.test.base import APILicensedTest
from ee.models.rbac.role import Role, RoleMembership
from posthog.constants import AvailableFeature
from posthog.models.dashboard import Dashboard
from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.models.notebook.notebook import Notebook
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.utils import render_template


class BaseAccessControlTest(APILicensedTest):
    def setUp(self):
        super().setUp()
        self.organization.available_features = [
            AvailableFeature.PROJECT_BASED_PERMISSIONING,
            AvailableFeature.ROLE_BASED_ACCESS,
        ]
        self.organization.save()

    def _put_project_access_control(self, data=None):
        payload = {"access_level": "admin"}

        if data:
            payload.update(data)

        return self.client.put(
            "/api/projects/@current/access_controls",
            payload,
        )

    def _put_global_access_control(self, data=None):
        payload = {"access_level": "editor"}
        if data:
            payload.update(data)

        return self.client.put(
            "/api/projects/@current/global_access_controls",
            payload,
        )

    def _org_membership(self, level: OrganizationMembership.Level = OrganizationMembership.Level.ADMIN):
        self.organization_membership.level = level
        self.organization_membership.save()


class TestAccessControlProjectLevelAPI(BaseAccessControlTest):
    def test_project_change_rejected_if_not_org_admin(self):
        self._org_membership(OrganizationMembership.Level.MEMBER)
        res = self._put_project_access_control()
        assert res.status_code == status.HTTP_403_FORBIDDEN, res.json()

    def test_project_change_accepted_if_org_admin(self):
        self._org_membership(OrganizationMembership.Level.ADMIN)
        res = self._put_project_access_control()
        assert res.status_code == status.HTTP_200_OK, res.json()

    def test_project_change_accepted_if_org_owner(self):
        self._org_membership(OrganizationMembership.Level.OWNER)
        res = self._put_project_access_control()
        assert res.status_code == status.HTTP_200_OK, res.json()

    def test_project_removed_with_null(self):
        self._org_membership(OrganizationMembership.Level.OWNER)
        res = self._put_project_access_control()
        res = self._put_project_access_control({"access_level": None})
        assert res.status_code == status.HTTP_204_NO_CONTENT

    def test_project_change_if_in_access_control(self):
        self._org_membership(OrganizationMembership.Level.ADMIN)
        # Add ourselves to access
        res = self._put_project_access_control(
            {"organization_member": str(self.organization_membership.id), "access_level": "admin"}
        )
        assert res.status_code == status.HTTP_200_OK, res.json()

        self._org_membership(OrganizationMembership.Level.MEMBER)

        # Now change ourselves to a member
        res = self._put_project_access_control(
            {"organization_member": str(self.organization_membership.id), "access_level": "member"}
        )
        assert res.status_code == status.HTTP_200_OK, res.json()
        assert res.json()["access_level"] == "member"

        # Now try and change our own membership and fail!
        res = self._put_project_access_control(
            {"organization_member": str(self.organization_membership.id), "access_level": "admin"}
        )
        assert res.status_code == status.HTTP_403_FORBIDDEN
        assert res.json()["detail"] == "Must be admin to modify project permissions."

    def test_project_change_rejected_if_not_in_organization(self):
        self.organization_membership.delete()
        res = self._put_project_access_control(
            {"organization_member": str(self.organization_membership.id), "access_level": "admin"}
        )
        assert res.status_code == status.HTTP_404_NOT_FOUND, res.json()

    def test_project_change_rejected_if_bad_access_level(self):
        self._org_membership(OrganizationMembership.Level.ADMIN)
        res = self._put_project_access_control({"access_level": "bad"})
        assert res.status_code == status.HTTP_400_BAD_REQUEST, res.json()
        assert res.json()["detail"] == "Invalid access level. Must be one of: none, member, admin", res.json()


class TestAccessControlResourceLevelAPI(BaseAccessControlTest):
    def setUp(self):
        super().setUp()

        self.notebook = Notebook.objects.create(
            team=self.team, created_by=self.user, short_id="0", title="first notebook"
        )

        self.other_user = self._create_user("other_user")
        self.other_user_notebook = Notebook.objects.create(
            team=self.team, created_by=self.other_user, short_id="1", title="first notebook"
        )

    def _get_access_controls(self):
        return self.client.get(f"/api/projects/@current/notebooks/{self.notebook.short_id}/access_controls")

    def _put_access_control(self, data=None, notebook_id=None):
        payload = {
            "access_level": "editor",
        }

        if data:
            payload.update(data)
        return self.client.put(
            f"/api/projects/@current/notebooks/{notebook_id or self.notebook.short_id}/access_controls",
            payload,
        )

    def test_get_access_controls(self):
        self._org_membership(OrganizationMembership.Level.MEMBER)
        res = self._get_access_controls()
        assert res.status_code == status.HTTP_200_OK, res.json()
        assert res.json() == {
            "access_controls": [],
            "available_access_levels": ["none", "viewer", "editor"],
            "user_access_level": "editor",
            "default_access_level": "editor",
            "user_can_edit_access_levels": True,
        }

    def test_change_rejected_if_not_org_admin(self):
        self._org_membership(OrganizationMembership.Level.MEMBER)
        res = self._put_access_control(notebook_id=self.other_user_notebook.short_id)
        assert res.status_code == status.HTTP_403_FORBIDDEN, res.json()

    def test_change_accepted_if_org_admin(self):
        self._org_membership(OrganizationMembership.Level.ADMIN)
        res = self._put_access_control(notebook_id=self.other_user_notebook.short_id)
        assert res.status_code == status.HTTP_200_OK, res.json()

    def test_change_accepted_if_creator_of_the_resource(self):
        self._org_membership(OrganizationMembership.Level.MEMBER)
        res = self._put_access_control(notebook_id=self.notebook.short_id)
        assert res.status_code == status.HTTP_200_OK, res.json()


class TestGlobalAccessControlsPermissions(BaseAccessControlTest):
    def setUp(self):
        super().setUp()

        self.role = Role.objects.create(name="Engineers", organization=self.organization)
        self.role_membership = RoleMembership.objects.create(user=self.user, role=self.role)

    def test_admin_can_always_access(self):
        self._org_membership(OrganizationMembership.Level.ADMIN)
        assert (
            self._put_global_access_control({"resource": "feature_flag", "access_level": "none"}).status_code
            == status.HTTP_200_OK
        )
        assert self.client.get("/api/projects/@current/feature_flags").status_code == status.HTTP_200_OK

    def test_forbidden_access_if_resource_wide_control_in_place(self):
        self._org_membership(OrganizationMembership.Level.ADMIN)
        assert (
            self._put_global_access_control({"resource": "feature_flag", "access_level": "none"}).status_code
            == status.HTTP_200_OK
        )
        self._org_membership(OrganizationMembership.Level.MEMBER)

        assert self.client.get("/api/projects/@current/feature_flags").status_code == status.HTTP_403_FORBIDDEN
        assert self.client.post("/api/projects/@current/feature_flags").status_code == status.HTTP_403_FORBIDDEN

    def test_forbidden_write_access_if_resource_wide_control_in_place(self):
        self._org_membership(OrganizationMembership.Level.ADMIN)
        assert (
            self._put_global_access_control({"resource": "feature_flag", "access_level": "viewer"}).status_code
            == status.HTTP_200_OK
        )
        self._org_membership(OrganizationMembership.Level.MEMBER)

        assert self.client.get("/api/projects/@current/feature_flags").status_code == status.HTTP_200_OK
        assert self.client.post("/api/projects/@current/feature_flags").status_code == status.HTTP_403_FORBIDDEN

    def test_access_granted_with_granted_role(self):
        self._org_membership(OrganizationMembership.Level.ADMIN)
        assert (
            self._put_global_access_control({"resource": "feature_flag", "access_level": "none"}).status_code
            == status.HTTP_200_OK
        )
        assert (
            self._put_global_access_control(
                {"resource": "feature_flag", "access_level": "viewer", "role": self.role.id}
            ).status_code
            == status.HTTP_200_OK
        )
        self._org_membership(OrganizationMembership.Level.MEMBER)

        assert self.client.get("/api/projects/@current/feature_flags").status_code == status.HTTP_200_OK
        assert self.client.post("/api/projects/@current/feature_flags").status_code == status.HTTP_403_FORBIDDEN

        self.role_membership.delete()
        assert self.client.get("/api/projects/@current/feature_flags").status_code == status.HTTP_403_FORBIDDEN


class TestAccessControlPermissions(BaseAccessControlTest):
    """
    Test actual permissions being applied for a resource (notebooks as an example)
    """

    def setUp(self):
        super().setUp()
        self.other_user = self._create_user("other_user")

        self.other_user_notebook = Notebook.objects.create(
            team=self.team, created_by=self.other_user, title="not my notebook"
        )

        self.notebook = Notebook.objects.create(team=self.team, created_by=self.user, title="my notebook")

    def _post_notebook(self):
        return self.client.post("/api/projects/@current/notebooks/", {"title": "notebook"})

    def _patch_notebook(self, id: str):
        return self.client.patch(f"/api/projects/@current/notebooks/{id}", {"title": "new-title"})

    def _get_notebook(self, id: str):
        return self.client.get(f"/api/projects/@current/notebooks/{id}")

    def _put_notebook_access_control(self, notebook_id: str, data=None):
        payload = {
            "access_level": "editor",
        }

        if data:
            payload.update(data)
        return self.client.put(
            f"/api/projects/@current/notebooks/{notebook_id}/access_controls",
            payload,
        )

    def test_default_allows_all_access(self):
        self._org_membership(OrganizationMembership.Level.MEMBER)
        assert self._get_notebook(self.other_user_notebook.short_id).status_code == status.HTTP_200_OK
        assert self._patch_notebook(id=self.other_user_notebook.short_id).status_code == status.HTTP_200_OK
        res = self._post_notebook()
        assert res.status_code == status.HTTP_201_CREATED
        assert self._patch_notebook(id=res.json()["short_id"]).status_code == status.HTTP_200_OK

    def test_rejects_all_access_without_project_access(self):
        self._org_membership(OrganizationMembership.Level.ADMIN)
        assert self._put_project_access_control({"access_level": "none"}).status_code == status.HTTP_200_OK
        self._org_membership(OrganizationMembership.Level.MEMBER)

        assert self._get_notebook(self.other_user_notebook.short_id).status_code == status.HTTP_403_FORBIDDEN
        assert self._patch_notebook(id=self.other_user_notebook.short_id).status_code == status.HTTP_403_FORBIDDEN
        assert self._post_notebook().status_code == status.HTTP_403_FORBIDDEN

    def test_permits_access_with_member_control(self):
        self._org_membership(OrganizationMembership.Level.ADMIN)
        assert self._put_project_access_control({"access_level": "none"}).status_code == status.HTTP_200_OK
        assert (
            self._put_project_access_control(
                {"access_level": "member", "organization_member": str(self.organization_membership.id)}
            ).status_code
            == status.HTTP_200_OK
        )
        self._org_membership(OrganizationMembership.Level.MEMBER)

        assert self._get_notebook(self.other_user_notebook.short_id).status_code == status.HTTP_200_OK
        assert self._patch_notebook(id=self.other_user_notebook.short_id).status_code == status.HTTP_200_OK
        assert self._post_notebook().status_code == status.HTTP_201_CREATED

    def test_rejects_edit_access_with_resource_control(self):
        self._org_membership(OrganizationMembership.Level.ADMIN)
        # Set other notebook to only allow view access by default
        assert (
            self._put_notebook_access_control(self.other_user_notebook.short_id, {"access_level": "viewer"}).status_code
            == status.HTTP_200_OK
        )
        self._org_membership(OrganizationMembership.Level.MEMBER)

        assert self._get_notebook(self.other_user_notebook.short_id).status_code == status.HTTP_200_OK
        assert self._patch_notebook(id=self.other_user_notebook.short_id).status_code == status.HTTP_403_FORBIDDEN
        assert self._post_notebook().status_code == status.HTTP_201_CREATED

    def test_rejects_view_access_if_not_creator(self):
        self._org_membership(OrganizationMembership.Level.ADMIN)
        # Set other notebook to only allow view access by default
        assert (
            self._put_notebook_access_control(self.other_user_notebook.short_id, {"access_level": "none"}).status_code
            == status.HTTP_200_OK
        )
        assert (
            self._put_notebook_access_control(self.notebook.short_id, {"access_level": "none"}).status_code
            == status.HTTP_200_OK
        )
        self._org_membership(OrganizationMembership.Level.MEMBER)

        # Access to other notebook is denied
        assert self._get_notebook(self.other_user_notebook.short_id).status_code == status.HTTP_403_FORBIDDEN
        assert self._patch_notebook(id=self.other_user_notebook.short_id).status_code == status.HTTP_403_FORBIDDEN
        # As creator, access to my notebook is still permitted
        assert self._get_notebook(self.notebook.short_id).status_code == status.HTTP_200_OK
        assert self._patch_notebook(id=self.notebook.short_id).status_code == status.HTTP_200_OK

    def test_org_level_endpoints_work(self):
        assert self.client.get("/api/organizations/@current/plugins").status_code == status.HTTP_200_OK


class TestAccessControlQueryCounts(BaseAccessControlTest):
    def setUp(self):
        super().setUp()
        self.other_user = self._create_user("other_user")

        self.other_user_notebook = Notebook.objects.create(
            team=self.team, created_by=self.other_user, title="not my notebook"
        )

        self.notebook = Notebook.objects.create(team=self.team, created_by=self.user, title="my notebook")

        # Baseline call to trigger caching of one off things like instance settings
        self.client.get(f"/api/projects/@current/notebooks/{self.notebook.short_id}")

    def test_query_counts(self):
        self._org_membership(OrganizationMembership.Level.MEMBER)
        my_dashboard = Dashboard.objects.create(team=self.team, created_by=self.user)
        other_user_dashboard = Dashboard.objects.create(team=self.team, created_by=self.other_user)

        # Baseline query (triggers any first time cache things)
        self.client.get(f"/api/projects/@current/notebooks/{self.notebook.short_id}")
        baseline = 11

        # Access controls total 2 extra queries - 1 for org membership, 1 for the user roles, 1 for the preloaded access controls
        with self.assertNumQueries(baseline + 4):
            self.client.get(f"/api/projects/@current/dashboards/{my_dashboard.id}?no_items_field=true")

        # Accessing a different users dashboard doesn't +1 as the preload works using the pk
        with self.assertNumQueries(baseline + 4):
            self.client.get(f"/api/projects/@current/dashboards/{other_user_dashboard.id}?no_items_field=true")

        baseline = 6
        # Getting my own notebook is the same as a dashboard - 2 extra queries
        with self.assertNumQueries(baseline + 4):
            self.client.get(f"/api/projects/@current/notebooks/{self.notebook.short_id}")

        # Except when accessing a different notebook where we _also_ need to check as we are not the creator and the pk is not the same (short_id)
        with self.assertNumQueries(baseline + 5):
            self.client.get(f"/api/projects/@current/notebooks/{self.other_user_notebook.short_id}")

        baseline = 4
        # Project access doesn't double query the object
        with self.assertNumQueries(baseline + 7):
            # We call this endpoint as we don't want to include all the extra queries that rendering the project uses
            self.client.get("/api/projects/@current/is_generating_demo_data")

        # When accessing the list of notebooks we have extra queries due to checking for role based access and filtering out items
        baseline = 7
        with self.assertNumQueries(baseline + 4):  # org, roles, preloaded access controls
            self.client.get("/api/projects/@current/notebooks/")

    def test_query_counts_with_preload_optimization(self):
        self._org_membership(OrganizationMembership.Level.MEMBER)
        my_dashboard = Dashboard.objects.create(team=self.team, created_by=self.user)
        other_user_dashboard = Dashboard.objects.create(team=self.team, created_by=self.other_user)

        # Baseline query (triggers any first time cache things)
        self.client.get(f"/api/projects/@current/notebooks/{self.notebook.short_id}")
        baseline = 11

        # Access controls total 2 extra queries - 1 for org membership, 1 for the user roles, 1 for the preloaded access controls
        with self.assertNumQueries(baseline + 4):
            self.client.get(f"/api/projects/@current/dashboards/{my_dashboard.id}?no_items_field=true")

        # Accessing a different users dashboard doesn't +1 as the preload works using the pk
        with self.assertNumQueries(baseline + 4):
            self.client.get(f"/api/projects/@current/dashboards/{other_user_dashboard.id}?no_items_field=true")

    def test_query_counts_only_adds_1_for_non_pk_resources(self):
        self._org_membership(OrganizationMembership.Level.MEMBER)
        # Baseline query (triggers any first time cache things)
        self.client.get(f"/api/projects/@current/notebooks/{self.notebook.short_id}")
        baseline = 11

        baseline = 6
        # Getting my own notebook is the same as a dashboard - 2 extra queries
        with self.assertNumQueries(baseline + 4):
            self.client.get(f"/api/projects/@current/notebooks/{self.notebook.short_id}")

        # Except when accessing a different notebook where we _also_ need to check as we are not the creator and the pk is not the same (short_id)
        with self.assertNumQueries(baseline + 5):
            self.client.get(f"/api/projects/@current/notebooks/{self.other_user_notebook.short_id}")

    def test_query_counts_stable_for_project_access(self):
        self._org_membership(OrganizationMembership.Level.MEMBER)
        baseline = 4
        # Project access doesn't double query the object
        with self.assertNumQueries(baseline + 7):
            # We call this endpoint as we don't want to include all the extra queries that rendering the project uses
            self.client.get("/api/projects/@current/is_generating_demo_data")

        # When accessing the list of notebooks we have extra queries due to checking for role based access and filtering out items
        baseline = 7
        with self.assertNumQueries(baseline + 4):  # org, roles, preloaded access controls
            self.client.get("/api/projects/@current/notebooks/")

    def test_query_counts_stable_when_listing_resources(self):
        # When accessing the list of notebooks we have extra queries due to checking for role based access and filtering out items
        baseline = 7
        with self.assertNumQueries(baseline + 4):  # org, roles, preloaded access controls
            self.client.get("/api/projects/@current/notebooks/")

    def test_query_counts_stable_when_listing_resources_including_access_control_info(self):
        for i in range(10):
            FeatureFlag.objects.create(team=self.team, created_by=self.other_user, key=f"flag-{i}")

        baseline = 42  # This is a lot! There is currently an n+1 issue with the legacy access control system
        with self.assertNumQueries(baseline + 6):  # org, roles, preloaded permissions acs, preloaded acs for the list
            self.client.get("/api/projects/@current/feature_flags/")

        for i in range(10):
            FeatureFlag.objects.create(team=self.team, created_by=self.other_user, key=f"flag-{10 + i}")

        baseline = baseline + (10 * 3)  # The existing access control adds 3 queries per item :(
        with self.assertNumQueries(baseline + 6):  # org, roles, preloaded permissions acs, preloaded acs for the list
            self.client.get("/api/projects/@current/feature_flags/")


class TestAccessControlFiltering(BaseAccessControlTest):
    def setUp(self):
        super().setUp()
        self.other_user = self._create_user("other_user")

        self.other_user_notebook = Notebook.objects.create(
            team=self.team, created_by=self.other_user, title="not my notebook"
        )

        self.notebook = Notebook.objects.create(team=self.team, created_by=self.user, title="my notebook")

    def _put_notebook_access_control(self, notebook_id: str, data=None):
        payload = {
            "access_level": "editor",
        }

        if data:
            payload.update(data)
        return self.client.put(
            f"/api/projects/@current/notebooks/{notebook_id}/access_controls",
            payload,
        )

    def _get_notebooks(self):
        return self.client.get("/api/projects/@current/notebooks/")

    def test_default_allows_all_access(self):
        self._org_membership(OrganizationMembership.Level.MEMBER)
        assert len(self._get_notebooks().json()["results"]) == 2

    def test_does_not_list_notebooks_without_access(self):
        self._org_membership(OrganizationMembership.Level.ADMIN)
        assert (
            self._put_notebook_access_control(self.other_user_notebook.short_id, {"access_level": "none"}).status_code
            == status.HTTP_200_OK
        )
        assert (
            self._put_notebook_access_control(self.notebook.short_id, {"access_level": "none"}).status_code
            == status.HTTP_200_OK
        )
        self._org_membership(OrganizationMembership.Level.MEMBER)

        res = self._get_notebooks()
        assert len(res.json()["results"]) == 1
        assert res.json()["results"][0]["id"] == str(self.notebook.id)

    def test_list_notebooks_with_explicit_access(self):
        self._org_membership(OrganizationMembership.Level.ADMIN)
        assert (
            self._put_notebook_access_control(self.other_user_notebook.short_id, {"access_level": "none"}).status_code
            == status.HTTP_200_OK
        )
        assert (
            self._put_notebook_access_control(
                self.other_user_notebook.short_id,
                {"organization_member": str(self.organization_membership.id), "access_level": "viewer"},
            ).status_code
            == status.HTTP_200_OK
        )
        self._org_membership(OrganizationMembership.Level.MEMBER)

        res = self._get_notebooks()
        assert len(res.json()["results"]) == 2

    def test_search_results_exclude_restricted_objects(self):
        res = self.client.get("/api/projects/@current/search?q=my notebook")
        assert len(res.json()["results"]) == 2

        self._org_membership(OrganizationMembership.Level.ADMIN)
        assert (
            self._put_notebook_access_control(self.other_user_notebook.short_id, {"access_level": "none"}).status_code
            == status.HTTP_200_OK
        )

        self._org_membership(OrganizationMembership.Level.MEMBER)

        res = self.client.get("/api/projects/@current/search?q=my notebook")
        assert len(res.json()["results"]) == 1


class TestAccessControlProjectFiltering(BaseAccessControlTest):
    """
    Projects are listed in multiple places and ways so we need to test all of them here
    """

    def setUp(self):
        super().setUp()
        self.other_team = Team.objects.create(organization=self.organization, name="other team")
        self.other_team_2 = Team.objects.create(organization=self.organization, name="other team 2")

    def _put_project_access_control_as_admin(self, team_id: int, data=None):
        self._org_membership(OrganizationMembership.Level.ADMIN)
        payload = {
            "access_level": "editor",
        }

        if data:
            payload.update(data)
        res = self.client.put(
            f"/api/projects/{team_id}/access_controls",
            payload,
        )

        self._org_membership(OrganizationMembership.Level.MEMBER)

        assert res.status_code == status.HTTP_200_OK, res.json()
        return res

    def _get_posthog_app_context(self):
        mock_template = MagicMock()
        with patch("posthog.utils.get_template", return_value=mock_template):
            mock_request = MagicMock()
            mock_request.user = self.user
            mock_request.GET = {}
            render_template("index.html", request=mock_request, context={})

            # Get the context passed to the template
            return json.loads(mock_template.render.call_args[0][0]["posthog_app_context"])

    def test_default_lists_all_projects(self):
        assert len(self.client.get("/api/projects").json()["results"]) == 3
        me_response = self.client.get("/api/users/@me").json()
        assert len(me_response["organization"]["teams"]) == 3

    def test_does_not_list_projects_without_access(self):
        self._put_project_access_control_as_admin(self.other_team.id, {"access_level": "none"})
        assert len(self.client.get("/api/projects").json()["results"]) == 2
        me_response = self.client.get("/api/users/@me").json()
        assert len(me_response["organization"]["teams"]) == 2

    def test_always_lists_all_projects_if_org_admin(self):
        self._put_project_access_control_as_admin(self.other_team.id, {"access_level": "none"})
        self._org_membership(OrganizationMembership.Level.ADMIN)
        assert len(self.client.get("/api/projects").json()["results"]) == 3
        me_response = self.client.get("/api/users/@me").json()
        assert len(me_response["organization"]["teams"]) == 3

    def test_template_render_filters_teams(self):
        app_context = self._get_posthog_app_context()
        assert len(app_context["current_user"]["organization"]["teams"]) == 3
        assert app_context["current_team"]["id"] == self.team.id
        assert app_context["current_team"]["user_access_level"] == "admin"

        self._put_project_access_control_as_admin(self.team.id, {"access_level": "none"})
        app_context = self._get_posthog_app_context()
        assert len(app_context["current_user"]["organization"]["teams"]) == 2
        assert app_context["current_team"]["id"] == self.team.id
        assert app_context["current_team"]["user_access_level"] == "none"


# TODO: Add tests to check that a dashboard can't be edited if the user doesn't have access
