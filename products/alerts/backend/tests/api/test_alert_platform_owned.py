from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models.scoping import team_scope

from products.alerts.backend.models.alert import AlertCheck
from products.alerts.backend.platform_cutover import cut_over_team
from products.alerts.backend.test.insight_alerts import create_insight_alert
from products.alerts_platform.backend.facade import testing as platform_testing


def _iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


class TestPlatformOwnedInsightAlert(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.now = datetime.now(UTC)
        self.alert = create_insight_alert(
            self.team,
            next_check_at=self.now + timedelta(minutes=3),
            last_checked_at=self.now - timedelta(hours=2),
        )
        AlertCheck.objects.create(alert_configuration=self.alert, calculated_value=1.0, state="Not firing")
        [cutover] = cut_over_team(self.team.id, now=self.now)
        assert cutover.skipped is None
        with team_scope(self.team.id):
            self.copy_id = platform_testing.copy_of(self.alert.id).id
        self.url = f"/api/projects/{self.team.id}/alerts"

    def _at(self, minutes_ago: int) -> datetime:
        return self.now - timedelta(minutes=minutes_ago)

    def _record(self, minutes_ago: int, state: str, *, value: float | None = None, error: str | None = None) -> None:
        platform_testing.record_check(
            self.copy_id,
            team_id=self.team.id,
            at=self._at(minutes_ago),
            previous_state="not_firing",
            state=state,
            value=value,
            error_message=error,
        )

    def _row(self, action: str, query: str = "") -> dict[str, Any]:
        if action == "list":
            response = self.client.get(f"{self.url}/")
            assert response.status_code == status.HTTP_200_OK
            [row] = response.json()["results"]
            return row
        response = self.client.get(f"{self.url}/{self.alert.id}/{query}")
        assert response.status_code == status.HTTP_200_OK
        return response.json()

    @parameterized.expand([("list",), ("retrieve",)])
    def test_a_moved_alert_shows_the_platform_state_and_last_check(self, action: str) -> None:
        self._record(30, "firing", value=150.0)
        with team_scope(self.team.id):
            platform_testing.start_firing(self.copy_id, team_id=self.team.id, at=self._at(30))

        row = self._row(action)

        assert (row["state"], row["last_checked_at"], row["last_value"]) == ("Firing", _iso(self._at(30)), 150.0)

    def test_a_moved_alert_lists_its_checks_from_the_platform(self) -> None:
        self._record(90, "not_firing", value=50.0)
        self._record(60, "firing", value=150.0)
        self._record(30, "errored", error="Query timed out")

        row = self._row("retrieve", "?checks_limit=2")

        assert row["checks_total"] == 3
        assert [(check["created_at"], check["state"], check["calculated_value"]) for check in row["checks"]] == [
            (_iso(self._at(30)), "Errored", None),
            (_iso(self._at(60)), "Firing", 150.0),
        ]
        # A platform error can carry an internal detail, so the history shows the generic message.
        assert row["checks"][0]["error"] == {
            "message": "This alert encountered an error. Check the alert configuration and try again."
        }
        past_the_end = self._row("retrieve", "?checks_offset=5")
        assert (past_the_end["checks_total"], past_the_end["checks"]) == (3, [])

    def test_a_platform_history_failure_falls_back_to_the_alerts_own_checks(self) -> None:
        self._record(30, "firing", value=150.0)

        with patch(
            "products.alerts.backend.platform_alert_reads.check_page_by_legacy_id",
            side_effect=RuntimeError("ClickHouse is down"),
        ):
            row = self._row("retrieve")

        assert [(check["state"], check["calculated_value"]) for check in row["checks"]] == [("Not firing", 1.0)]
