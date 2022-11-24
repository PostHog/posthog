from typing import Literal, Optional
from unittest import mock
from unittest.mock import Mock, patch

from django.http import HttpResponse
from rest_framework import status

from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team
from posthog.api.test.test_user import create_user
from posthog.helpers.dashboard_templates import create_global_templates
from posthog.models import OrganizationMembership, User
from posthog.test.base import APIBaseTest, QueryMatchingTest

default_templates = [
    {"id": mock.ANY, "template_name": "Product analytics", "scope": "global"},
]


class TestDashboardTemplates(APIBaseTest, QueryMatchingTest):
    def setUp(self):
        super().setUp()

        self.org_admin = User.objects.create_and_join(
            organization=self.organization,
            email="org-admin-user@posthog.com",
            password=None,
            level=OrganizationMembership.Level.ADMIN,
        )

        self.org_one_staff_user = create_user("staff_user@posthog.com", password="1234", organization=self.organization)
        self.org_one_staff_user.is_staff = True
        self.org_one_staff_user.save()

        self.org_one_team_two = create_team(organization=self.organization)
        self.org_one_team_two_user = create_user(
            email="team_two@posthog.com", password="1234", organization=self.organization
        )
        self.org_one_team_two_user.current_team = self.org_one_team_two
        self.org_one_team_two_user.save()

        self.another_organization = create_organization(name="org two")
        self.org_two_team_one = create_team(organization=self.another_organization)
        self.org_two_user = create_user(
            email="team_two_user@posthog.com", password="1234", organization=self.another_organization
        )

    def test_create_defaults_overwrites_not_duplicates(self) -> None:
        create_global_templates([{"name": "a"}, {"name": "b"}])
        create_global_templates([{"name": "a"}, {"name": "b"}])

        assert len(self.client.get("/api/projects/@current/dashboard_templates/?basic=true").json()["results"]) == 2

    def test_create_refuses_to_duplicate(self) -> None:
        self._create_template()
        self._create_template(expected_status=status.HTTP_400_BAD_REQUEST)

        assert len(self.client.get("/api/projects/@current/dashboard_templates/?basic=true").json()["results"]) == 2

    def test_can_create_template(self) -> None:
        response = self._create_template()

        self.assertEqual(response.json()["template_name"], "Test template")
        self.assertEqual(response.json()["tags"], ["test"])
        self.assertEqual(response.json()["scope"], "project")
        self.assertEqual(response.json()["tiles"][0]["body"], "Test template text")

    def test_org_admin_can_create_template_in_organization_scope(self) -> None:
        self.client.force_login(self.org_admin)

        response = self._create_template(scope="organization")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        self.assertEqual(response.json()["scope"], "organization")

    def test_normal_user_cannot_create_template_in_global_scope(self) -> None:
        self._create_template(scope="global", expected_status=status.HTTP_403_FORBIDDEN)

    def test_normal_user_cannot_delete_template_in_global_scope(self) -> None:
        list_response = self.client.get(f"/api/projects/{self.team.id}/dashboard_templates/?basic=true")
        global_template = next(r for r in list_response.json()["results"] if r["scope"] == "global")
        delete_response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboard_templates/{global_template.get('id')}?basic=true",
            {"deleted": "true"},
        )
        self.assertEqual(delete_response.status_code, status.HTTP_403_FORBIDDEN, delete_response.json())

    def test_normal_user_cannot_rename_template_in_global_scope(self) -> None:
        list_response = self.client.get(f"/api/projects/{self.team.id}/dashboard_templates/?basic=true")
        global_template = next(r for r in list_response.json()["results"] if r["scope"] == "global")
        rename_response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboard_templates/{global_template.get('id')}?basic=true",
            {"template_name": "renamed"},
        )
        self.assertEqual(rename_response.status_code, status.HTTP_403_FORBIDDEN, rename_response.json())

    def test_staff_user_can_create_template_in_global_scope(self) -> None:
        self.client.force_login(self.org_one_staff_user)

        response = self._create_template(scope="global")

        self.assertEqual(response.json()["scope"], "global")

    def test_normal_user_cannot_create_template_in_organization_scope(self) -> None:
        self._create_template(scope="organization", expected_status=status.HTTP_403_FORBIDDEN)

    def test_normal_user_cannot_delete_template_in_organization_scope(self) -> None:
        self.client.force_login(self.org_admin)
        self._create_template("in org scope", scope="organization")

        self.client.force_login(self.user)

        list_response = self.client.get(f"/api/projects/{self.team.id}/dashboard_templates/?basic=true")
        global_template = next(r for r in list_response.json()["results"] if r["scope"] == "organization")
        delete_response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboard_templates/{global_template.get('id')}?basic=true",
            {"deleted": "true"},
        )
        self.assertEqual(delete_response.status_code, status.HTTP_403_FORBIDDEN, delete_response.json())

    def test_normal_user_cannot_rename_template_in_organization_scope(self) -> None:
        self.client.force_login(self.org_admin)
        self._create_template("in org scope", scope="organization")

        self.client.force_login(self.user)

        list_response = self.client.get(f"/api/projects/{self.team.id}/dashboard_templates/?basic=true")
        global_template = next(r for r in list_response.json()["results"] if r["scope"] == "organization")
        rename_response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboard_templates/{global_template.get('id')}?basic=true",
            {"template_name": "renamed"},
        )
        self.assertEqual(rename_response.status_code, status.HTTP_403_FORBIDDEN, rename_response.json())

    def test_cannot_create_templates_in_other_organization(self) -> None:
        self.client.force_login(self.org_two_user)
        self._create_template("a", team_id=self.team.id, expected_status=status.HTTP_403_FORBIDDEN)

    def test_can_list_templates_for_use_in_UI(self) -> None:

        a_response = self._create_template("a")  # only visible in Team One
        b_response = self._create_template("b")  # only visible in Team One

        self.client.force_login(self.org_admin)
        c_response = self._create_template("c", scope="organization")  # only visible in Org One

        self.client.force_login(self.org_one_staff_user)
        d_response = self._create_template("d", scope="global")  # visible in all orgs

        self.client.force_login(self.org_one_team_two_user)
        e_response = self._create_template(
            "e", scope="project", team_id=self.org_one_team_two.id
        )  # only visible in Team Two

        self.client.force_login(self.org_two_user)
        f_response = self._create_template("f", team_id=self.org_two_team_one.id)  # only visible in other organization

        team_one_expected_templates = default_templates + [
            {"id": a_response.json()["id"], "template_name": "a", "scope": "project"},
            {"id": b_response.json()["id"], "template_name": "b", "scope": "project"},
            {"id": c_response.json()["id"], "template_name": "c", "scope": "organization"},
            {"id": d_response.json()["id"], "template_name": "d", "scope": "global"},
        ]

        self.client.force_login(self.user)
        list_response = self.client.get(f"/api/projects/{self.team.id}/dashboard_templates/?basic=true")
        self.assertEqual(list_response.status_code, status.HTTP_200_OK, list_response.json())

        assert sorted(list_response.json()["results"], key=lambda x: x["template_name"]) == team_one_expected_templates

        team_two_expected_templates = default_templates + [
            {"id": c_response.json()["id"], "template_name": "c", "scope": "organization"},
            {"id": d_response.json()["id"], "template_name": "d", "scope": "global"},
            {"id": e_response.json()["id"], "template_name": "e", "scope": "project"},
        ]

        self.client.force_login(self.org_one_team_two_user)
        list_response = self.client.get(f"/api/projects/{self.org_one_team_two.id}/dashboard_templates/?basic=true")
        self.assertEqual(list_response.status_code, status.HTTP_200_OK, list_response.json())

        assert sorted(list_response.json()["results"], key=lambda x: x["template_name"]) == team_two_expected_templates

        team_three_expected_templates = default_templates + [
            {"id": d_response.json()["id"], "template_name": "d", "scope": "global"},
            {"id": f_response.json()["id"], "template_name": "f", "scope": "project"},
        ]

        self.client.force_login(self.org_two_user)
        list_response = self.client.get(f"/api/projects/{self.org_two_team_one.id}/dashboard_templates/?basic=true")
        self.assertEqual(list_response.status_code, status.HTTP_200_OK, list_response.json())

        assert (
            sorted(list_response.json()["results"], key=lambda x: x["template_name"]) == team_three_expected_templates
        )

    def test_create_dashboard_from_template(self) -> None:
        a_response = self._create_template("a")

        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/", {"name": "another", "use_template": a_response.json()["id"]}
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["creation_mode"], "template")
        self.assertEqual(len(response.json()["tiles"]), 2)
        self.assertEqual(response.json()["tags"], [])  # not licensed so no tags
        self.assertEqual(response.json()["tiles"][0]["text"]["body"], "Test template text")

    def test_rename_template(self) -> None:
        a_response = self._create_template("a")

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboard_templates/{a_response.json().get('id')}?basic=true",
            {"template_name": "a new name, for a new age"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        self.assertEqual(response.json()["template_name"], "a new name, for a new age")

    def test_cannot_rename_template_with_blank_name(self) -> None:
        a_response = self._create_template("a")

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboard_templates/{a_response.json().get('id')}?basic=true",
            {"template_name": "     "},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json())

    def test_soft_delete_template(self) -> None:
        a_response = self._create_template("a")
        self._create_template("b")

        list_response = self.client.get(f"/api/projects/{self.team.id}/dashboard_templates/?basic=true")
        assert len(list_response.json()["results"]) == 3

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboard_templates/{a_response.json().get('id')}?basic=true",
            {"deleted": "true"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())

        list_response = self.client.get(f"/api/projects/{self.team.id}/dashboard_templates/?basic=true")

        assert len(list_response.json()["results"]) == 2
        assert [r["template_name"] for r in list_response.json()["results"]] == [
            "Product analytics",
            "b",
        ]

    def test_get_individual_template(self) -> None:
        a_response = self._create_template("a")

        response = self.client.get(f"/api/projects/{self.team.id}/dashboard_templates/{a_response.json().get('id')}")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        self.assertEqual(response.json()["template_name"], "a")
        self.assertEqual(response.json()["scope"], "project")
        self.assertTrue(len(response.json()["tiles"]) > 0)

    def test_normal_user_cannot_refresh_from_template_repository(self) -> None:
        refresh_response = self.client.post(
            f"/api/projects/{self.team.id}/dashboard_templates/refresh_global_templates"
        )

        self.assertEqual(refresh_response.status_code, status.HTTP_403_FORBIDDEN, refresh_response.json())

    def test_staff_user_can_refresh_from_template_repository(self) -> None:
        self.client.force_login(self.org_one_staff_user)
        refresh_response = self.client.post(
            f"/api/projects/{self.team.id}/dashboard_templates/refresh_global_templates"
        )

        self.assertEqual(refresh_response.status_code, status.HTTP_201_CREATED, refresh_response.json())

    @patch("posthog.api.dashboard_templates.AsyncResult")
    def test_staff_user_can_poll_for_status_of_refresh_from_template_repository(self, patched_async_result) -> None:
        self.client.force_login(self.org_one_staff_user)

        # the patched_async_result when called returns a mock which has property state = "SUCCESS
        patched_async_result.return_value = Mock(status="SUCCESS")

        refresh_response = self.client.get(
            f"/api/projects/{self.team.id}/dashboard_templates/refresh_global_templates?task_id=abcdefgh"
        )

        self.assertEqual(refresh_response.status_code, status.HTTP_200_OK, refresh_response.json())
        self.assertEqual(refresh_response.json()["task_status"], "SUCCESS")

    def _create_template(
        self,
        name: str = "Test template",
        scope: Literal["project", "organization", "global"] = "project",
        expected_status: int = status.HTTP_201_CREATED,
        team_id: Optional[int] = None,
    ) -> HttpResponse:
        if not team_id:
            team_id = self.team.id

        create_response = self.client.post(
            f"/api/projects/{team_id}/dashboard_templates/",
            data={
                "template_name": name,
                "source_dashboard": 1,
                "dashboard_description": "",
                "tags": ["test"],
                "scope": scope,
                "tiles": [
                    {
                        "type": "TEXT",
                        "layouts": {},  # empty layouts should be valid too
                        "body": "Test template text",
                    },
                    {
                        "type": "INSIGHT",
                        "name": "Test template insight",
                        "layouts": {"lg": {"x": 0, "y": 0, "w": 6, "h": 3}},
                        "filters": {"insight": "TRENDS"},
                    },
                ],
            },
        )
        self.assertEqual(create_response.status_code, expected_status, create_response.json())
        return create_response
