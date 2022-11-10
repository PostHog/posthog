from rest_framework import status

from posthog.test.base import APIBaseTest, QueryMatchingTest


class TestDashboardTemplates(APIBaseTest, QueryMatchingTest):
    def test_can_create_template(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboard_templates/",
            data={
                "template_name": "Test template",
                "source_dashboard": 1,
                "dashboard_name": "Test dashboard",
                "dashboard_description": "",
                "tags": ["test"],
                "tiles": [
                    {
                        "type": "TEXT",
                        "layouts": {"lg": {"x": 0, "y": 0, "w": 6, "h": 3}},
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
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        self.assertEqual(response.json()["template_name"], "Test template")
        self.assertEqual(response.json()["tags"], ["test"])
        self.assertEqual(response.json()["tiles"][0]["body"], "Test template text")
