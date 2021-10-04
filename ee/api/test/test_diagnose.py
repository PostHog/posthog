from typing import Any, Dict

import pytest
from django.test import Client
from freezegun import freeze_time

from posthog.test.base import BaseTest


@pytest.mark.clickhouse_only
class DiagnoseTest(BaseTest):
    def test_requires_authn(self):
        response = get_event_odds_ratio(
            client=self.client,
            team_id=self.team.pk,
            source_event="test_event",
            target_event="test_event",
            date_from="2020-01-01",
            date_to="2020-01-01",
        )
        assert response.status_code == 401

    def test_event_correlation_endpoint(self):
        with freeze_time("2020-01-01"):
            self.client.force_login(self.user)

            odds = get_event_odds_ratio_ok(
                client=self.client,
                team_id=self.team.pk,
                source_event="pageview",
                target_event="signup",
                date_from="2020-01-01",
                date_to="2020-02-02",
            )

        self.assertEqual(
            odds,
            {
                "is_cached": False,
                "last_refresh": "2020-01-01T00:00:00Z",
                "result": {"events": [{"event": "watch video", "value": 1}]},
            },
        )


def get_event_odds_ratio(
    client: Client, team_id: int, source_event: str, target_event: str, date_from: str, date_to: str
):
    return client.get(
        f"/api/projects/{team_id}/insights/diagnose",
        data={
            "insight": "DIAGNOSE",
            "source_event": source_event,
            "target_event": target_event,
            "date_from": date_from,
            "date_to": date_to,
        },
    )


def get_event_odds_ratio_ok(
    client: Client, team_id: int, source_event: str, target_event: str, date_from: str, date_to: str
) -> Dict[str, Any]:
    response = get_event_odds_ratio(
        client=client,
        team_id=team_id,
        source_event=source_event,
        target_event=target_event,
        date_from=date_from,
        date_to=date_to,
    )

    assert response.status_code == 200
    return response.json()
