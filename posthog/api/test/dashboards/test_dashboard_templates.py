from typing import Literal, Optional
from unittest import mock

from django.http import HttpResponse
from rest_framework import status

from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team
from posthog.api.test.test_user import create_user
from posthog.test.base import APIBaseTest, QueryMatchingTest

default_templates = [
    {"id": mock.ANY, "template_name": "Product analytics", "scope": "global"},
    {"id": mock.ANY, "template_name": "Website traffic", "scope": "global"},
]


class TestDashboardTemplates(APIBaseTest, QueryMatchingTest):
    def test_can_create_template(self) -> None:
        response = self._create_template()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        self.assertEqual(response.json()["template_name"], "Test template")
        self.assertEqual(response.json()["tags"], ["test"])
        self.assertEqual(response.json()["scope"], "project")
        self.assertEqual(response.json()["tiles"][0]["body"], "Test template text")

    def test_can_create_template_in_organization_scope(self) -> None:
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
        self.user.is_staff = True
        self.user.save()

        response = self._create_template(scope="global")

        self.assertEqual(response.json()["scope"], "global")

    def test_cannot_create_templates_in_other_organization(self) -> None:
        another_organization = create_organization(name="test")
        create_team(organization=another_organization)
        other_team_user = create_user(
            email="test_other_org@posthog.com", password="1234", organization=another_organization
        )

        self.client.force_login(other_team_user)
        self._create_template("a", team_id=self.team.id, expected_status=status.HTTP_403_FORBIDDEN)

    def test_can_list_templates_for_use_in_UI(self) -> None:
        team_two = create_team(organization=self.organization)
        team_two_user = create_user(email="team_two@posthog.com", password="1234", organization=self.organization)
        team_two_user.current_team = team_two
        team_two_user.save()

        another_organization = create_organization(name="test")
        team_three = create_team(organization=another_organization)
        team_three_user = create_user(
            email="test_other_org@posthog.com", password="1234", organization=another_organization
        )

        a_response = self._create_template("a")  # only visible in Team One
        b_response = self._create_template("b")  # only visible in Team One
        c_response = self._create_template("c", scope="organization")  # only visible in Org One

        self.user.is_staff = True
        self.user.save()

        d_response = self._create_template("d", scope="global")  # visible in all orgs

        self.client.force_login(team_two_user)
        e_response = self._create_template("e", scope="project", team_id=team_two.id)  # only visible in Team Two

        self.client.force_login(team_three_user)
        f_response = self._create_template("f", team_id=team_three.id)  # only visible in Team Three

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

        self.client.force_login(team_two_user)
        list_response = self.client.get(f"/api/projects/{team_two.id}/dashboard_templates/?basic=true")
        self.assertEqual(list_response.status_code, status.HTTP_200_OK, list_response.json())

        assert sorted(list_response.json()["results"], key=lambda x: x["template_name"]) == team_two_expected_templates

        team_three_expected_templates = default_templates + [
            {"id": d_response.json()["id"], "template_name": "d", "scope": "global"},
            {"id": f_response.json()["id"], "template_name": "f", "scope": "project"},
        ]

        self.client.force_login(team_three_user)
        list_response = self.client.get(f"/api/projects/{team_three.id}/dashboard_templates/?basic=true")
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
        assert len(list_response.json()["results"]) == 4

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboard_templates/{a_response.json().get('id')}?basic=true",
            {"deleted": "true"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())

        list_response = self.client.get(f"/api/projects/{self.team.id}/dashboard_templates/?basic=true")
        assert len(list_response.json()["results"]) == 3
        assert [r["template_name"] for r in list_response.json()["results"]] == [
            "Product analytics",
            "Website traffic",
            "b",
        ]

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
