from datetime import timedelta

from freezegun import freeze_time
from posthog.test.base import APIBaseTest

from django.utils import timezone

from parameterized import parameterized
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from posthog.api.advanced_activity_logs.viewset import activity_log_ordering
from posthog.models.activity_logging.activity_log import ActivityLog


@freeze_time("2024-01-01T12:00:00Z")
class TestActivityLogCursorOrdering(APIBaseTest):
    def _create_logs(self, count: int, same_timestamp: bool = False) -> None:
        stamp = timezone.now()
        for index in range(count):
            ActivityLog.objects.create(
                team_id=self.team.id,
                organization_id=self.organization.id,
                scope="FeatureFlag",
                activity="updated",
                item_id=str(index),
                created_at=stamp if same_timestamp else stamp + timedelta(minutes=index),
            )

    def test_cursor_page_size_is_honored(self):
        self._create_logs(12)

        response = self.client.get(f"/api/projects/{self.team.id}/advanced_activity_logs/?page_size=5")

        assert response.status_code == 200, response.json()
        assert len(response.json()["results"]) == 5
        assert response.json()["next"] is not None

    def test_page_size_above_the_maximum_is_rejected(self):
        response = self.client.get(f"/api/projects/{self.team.id}/advanced_activity_logs/?page_size=99999")

        assert response.status_code == 400
        assert response.json()["attr"] == "page_size"

    def test_follow_keeps_the_cursor_usable_and_picks_up_new_entries(self):
        self._create_logs(3)
        base = f"/api/projects/{self.team.id}/advanced_activity_logs/?ordering=created_at&page_size=10&follow=true"

        exhausted = self.client.get(base).json()
        assert len(exhausted["results"]) == 3
        tail = exhausted["next"]
        assert tail is not None, "following stream must hand back a resumable cursor"

        # Re-polling the tail returns nothing but keeps a usable cursor, as a poller expects.
        idle = self.client.get(tail).json()
        assert idle["results"] == []
        assert idle["next"] is not None

        ActivityLog.objects.create(
            team_id=self.team.id,
            organization_id=self.organization.id,
            scope="FeatureFlag",
            activity="updated",
            item_id="brand-new",
            created_at=timezone.now() + timedelta(hours=1),
        )

        assert [row["item_id"] for row in self.client.get(tail).json()["results"]] == ["brand-new"]

    @parameterized.expand(
        [
            ("descending_default", ""),
            ("ascending_default", "&ordering=created_at"),
            ("descending_even_when_following", "&follow=true"),
        ]
    )
    def test_streams_that_should_terminate_end_with_a_null_next(self, _name: str, extra: str):
        self._create_logs(3)

        body = self.client.get(f"/api/projects/{self.team.id}/advanced_activity_logs/?page_size=10{extra}").json()

        assert len(body["results"]) == 3
        assert body["next"] is None

    def test_ordering_always_carries_a_unique_tiebreak(self):
        factory = APIRequestFactory()

        assert activity_log_ordering(Request(factory.get("/"))) == ("-created_at", "-id")
        assert activity_log_ordering(Request(factory.get("/?ordering=created_at"))) == ("created_at", "id")

    def test_ascending_ordering_is_opt_in_and_descending_is_the_default(self):
        self._create_logs(3)

        base = f"/api/projects/{self.team.id}/advanced_activity_logs/"

        ascending = self.client.get(f"{base}?ordering=created_at")
        assert ascending.status_code == 200, ascending.json()
        assert [row["item_id"] for row in ascending.json()["results"]] == ["0", "1", "2"]

        default = self.client.get(base)
        assert [row["item_id"] for row in default.json()["results"]] == ["2", "1", "0"]

    def test_unknown_ordering_value_is_rejected(self):
        response = self.client.get(f"/api/projects/{self.team.id}/advanced_activity_logs/?ordering=scope")

        assert response.status_code == 400
        assert response.json()["attr"] == "ordering"

    def test_ascending_cursor_walk_covers_every_row(self):
        self._create_logs(25, same_timestamp=True)

        seen: list[str] = []
        url = f"/api/projects/{self.team.id}/advanced_activity_logs/?ordering=created_at&page_size=10"
        while url:
            response = self.client.get(url)
            assert response.status_code == 200, response.json()
            body = response.json()
            seen.extend(row["item_id"] for row in body["results"])
            url = body["next"]

        assert sorted(seen) == sorted(str(index) for index in range(25))

    def test_tied_timestamps_paginate_without_loss_or_repeats(self):
        self._create_logs(25, same_timestamp=True)

        seen: list[str] = []
        url = f"/api/projects/{self.team.id}/advanced_activity_logs/?page_size=10"
        while url:
            response = self.client.get(url)
            assert response.status_code == 200, response.json()
            body = response.json()
            seen.extend(row["item_id"] for row in body["results"])
            url = body["next"]

        assert sorted(seen) == sorted(str(index) for index in range(25))
