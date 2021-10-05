from typing import Any, Dict

import pytest
from django.test import Client
from freezegun import freeze_time

from posthog.test.base import BaseTest


@pytest.mark.clickhouse_only
class FunnelCorrelationTest(BaseTest):
    """
    TODO: fill in details of request structure. At the moment it's not needed as
    we just return mock data
    """

    def test_requires_authn(self):
        response = get_funnel_correlation(client=self.client, team_id=self.team.pk,)
        assert response.status_code == 401

    def test_event_correlation_endpoint(self):
        with freeze_time("2020-01-01"):
            self.client.force_login(self.user)

            odds = get_funnel_correlation_ok(client=self.client, team_id=self.team.pk,)

        self.assertEqual(
            odds,
            {
                "is_cached": False,
                "last_refresh": "2020-01-01T00:00:00Z",
                "result": {
                    "events": [
                        # Top 10
                        {"event": "Event A", "success_count": 1, "failure_count": 4, "odds_ratio": 10},
                        {"event": "Event B", "success_count": 1, "failure_count": 4, "odds_ratio": 9.4},
                        {"event": "Event C", "success_count": 1, "failure_count": 4, "odds_ratio": 5.4},
                        {"event": "Event D", "success_count": 1, "failure_count": 4, "odds_ratio": 3.4},
                        {"event": "Event E", "success_count": 1, "failure_count": 4, "odds_ratio": 2.6},
                        {"event": "Event F", "success_count": 1, "failure_count": 4, "odds_ratio": 2.5},
                        {"event": "Event G", "success_count": 1, "failure_count": 4, "odds_ratio": 2.1},
                        {"event": "Event H", "success_count": 1, "failure_count": 4, "odds_ratio": 2.0},
                        {"event": "Event I", "success_count": 1, "failure_count": 4, "odds_ratio": 1.5},
                        {"event": "Event J", "success_count": 1, "failure_count": 4, "odds_ratio": 1.2},
                    ]
                },
            },
        )


def get_funnel_correlation(client: Client, team_id: int):
    return client.get(f"/api/projects/{team_id}/insights/funnel/correlation")


def get_funnel_correlation_ok(client: Client, team_id: int,) -> Dict[str, Any]:
    response = get_funnel_correlation(client=client, team_id=team_id,)

    assert response.status_code == 200
    return response.json()
