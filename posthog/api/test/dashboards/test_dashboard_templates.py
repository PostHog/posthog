from django.http import HttpResponse
from rest_framework import status

from posthog.test.base import APIBaseTest, QueryMatchingTest


class TestDashboardTemplates(APIBaseTest, QueryMatchingTest):
    def test_can_create_template(self) -> None:
        response = self._create_template()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        self.assertEqual(response.json()["template_name"], "Test template")
        self.assertEqual(response.json()["tags"], ["test"])
        self.assertEqual(response.json()["tiles"][0]["body"], "Test template text")

    def test_can_list_templates_for_use_in_UI(self) -> None:
        a_response = self._create_template("a")
        b_response = self._create_template("b")
        c_response = self._create_template("c")

        templates = [
            {"id": a_response.json()["id"], "template_name": "a"},
            {"id": b_response.json()["id"], "template_name": "b"},
            {"id": c_response.json()["id"], "template_name": "c"},
        ]

        list_response = self.client.get(f"/api/projects/{self.team.id}/dashboard_templates/?basic=true")
        self.assertEqual(list_response.status_code, status.HTTP_200_OK, list_response.json())

        assert list_response.json() == {"count": 3, "next": None, "previous": None, "results": templates}

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

    def _create_template(self, name: str = "Test template") -> HttpResponse:
        create_response = self.client.post(
            f"/api/projects/{self.team.id}/dashboard_templates/",
            data={
                "template_name": name,
                "source_dashboard": 1,
                "dashboard_description": "",
                "tags": ["test"],
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
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED, create_response.json())
        return create_response
