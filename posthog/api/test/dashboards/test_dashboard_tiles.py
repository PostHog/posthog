from typing import Dict, List, Optional
from unittest.mock import ANY

from rest_framework import status

from posthog.api.test.dashboards import DashboardAPI
from posthog.models import DashboardTile, Organization, Team, User
from posthog.test.base import APIBaseTest, QueryMatchingTest


class TestDashboard(APIBaseTest, QueryMatchingTest):
    def setUp(self) -> None:
        super().setUp()
        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)

        other_org = Organization.objects.create(name="other org")
        self.other_org_team = Team.objects.create(name="other team", organization=other_org)
        self.other_org_user = User.objects.create_and_join(
            other_org, "other@org.com", "", current_team=self.other_org_team
        )

    def test_can_add_insight_to_a_dashboard(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "My dashboard"})
        insight_id, _ = self.dashboard_api.create_insight({"name": "My insight"})

        self.dashboard_api.add_insight_to_dashboard(insight_id, dashboard_id)

        dashboard = self.dashboard_api.get_dashboard(dashboard_id)
        assert dashboard["tiles"][0]["insight"]["id"] == insight_id

        insight = self.dashboard_api.get_insight(insight_id)
        assert insight["dashboards"] == [dashboard_id]

    def test_can_remove_insight_from_a_dashboard(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "My dashboard"})
        insight_id, _ = self.dashboard_api.create_insight({"name": "My insight"})

        self.dashboard_api.add_insight_to_dashboard(insight_id, dashboard_id)
        self.dashboard_api.remove_tile_from_dashboard(dashboard_id, insight_id=insight_id)

        dashboard = self.dashboard_api.get_dashboard(dashboard_id)
        assert dashboard["tiles"] == []

        insight = self.dashboard_api.get_insight(insight_id)
        assert insight["dashboards"] == []

    def test_cannot_add_insight_to_a_dashboard_in_another_team(self) -> None:
        self.client.force_login(self.other_org_user)
        dashboard_id, _ = self.dashboard_api.create_dashboard(
            data={"name": "My dashboard"}, team_id=self.other_org_team.id
        )

        self.client.force_login(self.user)
        insight_id, _ = self.dashboard_api.create_insight({"name": "My insight"})

        self.dashboard_api.add_insight_to_dashboard(insight_id, dashboard_id, expected_status=status.HTTP_403_FORBIDDEN)

        assert DashboardTile.objects.filter(dashboard_id=dashboard_id, insight_id=insight_id).exists() is False

    def test_cannot_add_insight_from_a_different_team_to_a_dashboard(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "My dashboard"})

        self.client.force_login(self.other_org_user)
        insight_id, _ = self.dashboard_api.create_insight({"name": "My insight"}, team_id=self.other_org_team.id)

        self.client.force_login(self.user)
        self.dashboard_api.add_insight_to_dashboard(insight_id, dashboard_id, expected_status=status.HTTP_403_FORBIDDEN)

    def test_cannot_add_insight_from_wrong_team(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "My dashboard"})
        insight_id, _ = self.dashboard_api.create_insight({"name": "My insight"})

        self.client.force_login(self.other_org_user)
        self.dashboard_api.add_insight_to_dashboard(insight_id, dashboard_id, expected_status=status.HTTP_403_FORBIDDEN)
        self.dashboard_api.add_insight_to_dashboard(
            insight_id,
            dashboard_id,
            team_id=self.other_org_team.id,
            expected_status=status.HTTP_403_FORBIDDEN,
        )

    def test_adding_insight_to_dashboard_updates_activity_log(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "My dashboard"})
        insight_id, insight_json = self.dashboard_api.create_insight({"name": "My insight"})

        self.dashboard_api.add_insight_to_dashboard(insight_id, dashboard_id)

        self._assert_logs_the_activity(
            insight_id,
            [
                {
                    "activity": "updated",
                    "created_at": ANY,
                    "detail": {
                        "changes": [
                            {
                                "action": "changed",
                                "after": [
                                    {
                                        "dashboard": {
                                            "id": dashboard_id,
                                            "name": "My dashboard",
                                        }
                                    }
                                ],
                                "before": [],
                                "field": "dashboards",
                                "type": "Insight",
                            }
                        ],
                        "name": "My insight",
                        "short_id": insight_json["short_id"],
                        "trigger": None,
                    },
                    "item_id": str(insight_id),
                    "scope": "Insight",
                    "user": {"email": "user1@posthog.com", "first_name": ""},
                },
                {
                    "activity": "created",
                    "created_at": ANY,
                    "detail": {
                        "changes": None,
                        "name": "My insight",
                        "short_id": insight_json["short_id"],
                        "trigger": None,
                    },
                    "item_id": str(insight_id),
                    "scope": "Insight",
                    "user": {"email": "user1@posthog.com", "first_name": ""},
                },
            ],
            expected_log_items=2,
        )

    def test_removing_insight_from_dashboard_updates_activity_log(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "My dashboard"})
        insight_id, insight_json = self.dashboard_api.create_insight({"name": "My insight"})

        self.dashboard_api.add_insight_to_dashboard(insight_id, dashboard_id)
        self.dashboard_api.remove_tile_from_dashboard(dashboard_id, insight_id=insight_id)

        self._assert_logs_the_activity(
            insight_id,
            [
                {
                    "activity": "updated",
                    "created_at": ANY,
                    "detail": {
                        "changes": [
                            {
                                "action": "changed",
                                "after": [],
                                "before": [
                                    {
                                        "dashboard": {
                                            "id": dashboard_id,
                                            "name": "My dashboard",
                                        }
                                    }
                                ],
                                "field": "dashboards",
                                "type": "Insight",
                            }
                        ],
                        "name": "My insight",
                        "short_id": insight_json["short_id"],
                        "trigger": None,
                    },
                    "item_id": str(insight_id),
                    "scope": "Insight",
                    "user": {"email": "user1@posthog.com", "first_name": ""},
                },
                {
                    "activity": "updated",
                    "created_at": ANY,
                    "detail": {
                        "changes": [
                            {
                                "action": "changed",
                                "after": [
                                    {
                                        "dashboard": {
                                            "id": dashboard_id,
                                            "name": "My dashboard",
                                        }
                                    }
                                ],
                                "before": [],
                                "field": "dashboards",
                                "type": "Insight",
                            }
                        ],
                        "name": "My insight",
                        "short_id": insight_json["short_id"],
                        "trigger": None,
                    },
                    "item_id": str(insight_id),
                    "scope": "Insight",
                    "user": {"email": "user1@posthog.com", "first_name": ""},
                },
                {
                    "activity": "created",
                    "created_at": ANY,
                    "detail": {
                        "changes": None,
                        "name": "My insight",
                        "short_id": insight_json["short_id"],
                        "trigger": None,
                    },
                    "item_id": str(insight_id),
                    "scope": "Insight",
                    "user": {"email": "user1@posthog.com", "first_name": ""},
                },
            ],
            expected_log_items=3,
        )

    def test_can_add_text_tile_to_dashboard(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "My dashboard"})

        self.dashboard_api.add_text_to_dashboard({"text": {"body": "test"}}, dashboard_id)
        self.dashboard_api.add_text_to_dashboard({"text": {"body": "second"}}, dashboard_id)

        dashboard = self.dashboard_api.get_dashboard(dashboard_id)
        assert dashboard["tiles"][0]["text"]["body"] == "test"
        assert dashboard["tiles"][1]["text"]["body"] == "second"

    def test_can_remove_tile_from_dashboard(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "My dashboard"})

        self.dashboard_api.add_text_to_dashboard({"text": {"body": "test", "team": self.team.pk}}, dashboard_id)

        dashboard = self.dashboard_api.get_dashboard(dashboard_id)
        text_tile = dashboard["tiles"][0]["text"]

        self.dashboard_api.remove_tile_from_dashboard(dashboard_id, text_id=text_tile["id"])

        dashboard = self.dashboard_api.get_dashboard(dashboard_id)
        assert dashboard["tiles"] == []

    def _get_insight_activity(self, insight_id: int, expected_status: int = status.HTTP_200_OK):
        url = f"/api/projects/{self.team.id}/insights/{insight_id}/activity"
        activity = self.client.get(url)
        self.assertEqual(activity.status_code, expected_status)
        return activity.json()

    def _assert_logs_the_activity(
        self,
        insight_id: int,
        expected: List[Dict],
        expected_log_items: Optional[int] = None,
    ) -> None:
        activity_response = self._get_insight_activity(insight_id)

        activity: List[Dict] = activity_response["results"]
        if expected_log_items:
            self.assertEqual(len(activity), expected_log_items)

        self.maxDiff = None
        self.assertEqual(activity, expected)
