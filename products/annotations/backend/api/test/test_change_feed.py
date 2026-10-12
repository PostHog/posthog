from datetime import UTC, datetime, timedelta

import time_machine
from posthog.test.base import APIBaseTest

from posthog.models import User
from posthog.models.activity_logging.activity_log import ActivityLog

from products.access_control.backend.models.access_control import AccessControl
from products.annotations.backend.models.annotation import Annotation
from products.error_tracking.backend.facade.testing import create_release

NOW = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)


class TestChangeFeed(APIBaseTest):
    def _log_flag_activity(self, *, at: datetime, activity: str, changed_fields: list[str]) -> None:
        ActivityLog.objects.create(
            team_id=self.team.id,
            organization_id=self.organization.id,
            user=self.user,
            scope="FeatureFlag",
            item_id="101",
            activity=activity,
            created_at=at,
            detail={
                "name": "new-checkout",
                "changes": [
                    {"type": "FeatureFlag", "action": "changed", "field": field, "before": None, "after": None}
                    for field in changed_fields
                ],
            },
        )

    def _create_annotation(self, *, at: datetime) -> None:
        Annotation.objects.create(
            team=self.team,
            organization=self.organization,
            content="Deploy checkout service",
            date_marker=at,
            scope=Annotation.Scope.PROJECT,
        )

    def _list(self, **params: str) -> dict:
        response = self.client.get(f"/api/projects/{self.team.id}/change_feed/", params)
        assert response.status_code == 200, response.json()
        return response.json()

    @time_machine.travel(NOW, tick=False)
    def test_merges_sources_newest_first_inside_the_window(self) -> None:
        self._log_flag_activity(at=NOW - timedelta(days=2), activity="created", changed_fields=[])
        self._log_flag_activity(at=NOW - timedelta(hours=2), activity="updated", changed_fields=["active", "active"])
        with time_machine.travel(NOW - timedelta(hours=1), tick=False):
            create_release(team_id=self.team.id, hash_id="checkout-1.4.0", version="1.4.0", project="checkout")
        self._create_annotation(at=NOW - timedelta(minutes=30))

        feed = self._list(date_from=(NOW - timedelta(hours=3)).isoformat())

        assert [(change["kind"], change["activity"]) for change in feed["results"]] == [
            ("annotation", "annotated"),
            ("release", "released"),
            ("feature_flag", "updated"),
        ]
        release, flag = feed["results"][1], feed["results"][2]
        assert (release["name"], release["service"]) == ("1.4.0", "checkout")
        assert (flag["name"], flag["changed_fields"], flag["actor_name"]) == (
            "new-checkout",
            ["active"],
            self.user.email,
        )
        assert feed["has_more"] is False

        truncated = self._list(date_from=(NOW - timedelta(hours=3)).isoformat(), limit="2")
        assert [change["kind"] for change in truncated["results"]] == ["annotation", "release"]
        assert truncated["has_more"] is True

    @time_machine.travel(NOW, tick=False)
    def test_leaves_out_changes_to_resources_the_user_cannot_view(self) -> None:
        self.organization.available_product_features = [{"key": "access_control", "name": "Access control"}]
        self.organization.save()
        member = User.objects.create_and_join(self.organization, "change-feed-member@example.com", "password")
        AccessControl.objects.create(resource="feature_flag", team=self.team, access_level="none")
        self._log_flag_activity(at=NOW - timedelta(hours=1), activity="updated", changed_fields=["filters"])
        self._create_annotation(at=NOW - timedelta(minutes=30))
        self.client.force_login(member)

        feed = self._list()

        assert [change["kind"] for change in feed["results"]] == ["annotation"]

    def test_rejects_a_window_that_ends_before_it_starts(self) -> None:
        response = self.client.get(
            f"/api/projects/{self.team.id}/change_feed/",
            {"date_from": NOW.isoformat(), "date_to": (NOW - timedelta(hours=1)).isoformat()},
        )

        assert response.status_code == 400
