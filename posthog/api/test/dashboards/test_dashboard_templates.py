from rest_framework import status

from posthog.test.base import APIBaseTest, QueryMatchingTest


class TestDashboardTemplates(APIBaseTest, QueryMatchingTest):
    def test_can_create_template(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboard_templates/",
            data={
                "name": "Test template",
                "source_dashboard": 1,
                "template": {
                    "name": "Test template text tile",
                    "tiles": [
                        {
                            "type": "TEXT",
                            "layouts": {"lg": {"x": 0, "y": 0, "w": 6, "h": 3}},
                            "body": "Test template text",
                        }
                    ],
                },
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        self.assertEqual(response.json()["name"], "Test template")
        self.assertEqual(response.json()["template"]["tiles"][0]["body"], "Test template text")
