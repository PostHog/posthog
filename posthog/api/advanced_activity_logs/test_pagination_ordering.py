from datetime import timedelta

import time_machine
from posthog.test.base import APIBaseTest

from django.utils import timezone

from parameterized import parameterized
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from posthog.api.advanced_activity_logs.viewset import activity_log_ordering
from posthog.models.activity_logging.activity_log import ActivityLog


@time_machine.travel("2024-01-01T12:00:00Z", tick=False)
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

    @parameterized.expand(
        [
            ("advanced_descending", "advanced_activity_logs", "", False),
            ("advanced_ascending", "advanced_activity_logs", "&ordering=created_at", False),
            ("advanced_page_number", "advanced_activity_logs", "", True),
            ("activity_log_descending", "activity_log", "", False),
            ("activity_log_page_number", "activity_log", "", True),
        ]
    )
    def test_org_scoped_walk_merges_team_and_org_rows_in_order(
        self, _name: str, endpoint: str, extra: str, page_number: bool
    ):
        self.team.receive_org_level_activity_logs = True
        self.team.save()
        other_team = self.create_team_with_organization(organization=self.organization)
        other_org = self.create_organization_with_features([])
        ActivityLog.objects.all().delete()

        stamp = timezone.now()
        expected: list[str] = []
        for index in range(23):
            if index % 3 == 0:
                team_id, organization_id, visible = None, self.organization.id, True
            elif index % 7 == 0:
                team_id, organization_id, visible = other_team.id, self.organization.id, False
            elif index % 11 == 0:
                team_id, organization_id, visible = None, other_org.id, False
            else:
                team_id, organization_id, visible = self.team.id, self.organization.id, True
            ActivityLog.objects.create(
                team_id=team_id,
                organization_id=organization_id,
                scope="FeatureFlag",
                activity="updated",
                item_id=str(index),
                created_at=stamp + timedelta(minutes=index // 2),
            )
            if visible:
                expected.append(str(index))

        ascending = "ordering=created_at" in extra
        rows = ActivityLog.objects.filter(item_id__in=expected).order_by(
            *(("created_at", "id") if ascending else ("-created_at", "-id"))
        )
        expected = [row.item_id for row in rows]

        seen: list[str] = []
        url: str | None = f"/api/projects/{self.team.id}/{endpoint}/?page_size=4{extra}"
        if page_number:
            url += "&page=1"
        while url:
            response = self.client.get(url)
            assert response.status_code == 200, response.json()
            body = response.json()
            seen.extend(row["item_id"] for row in body["results"])
            url = body["next"]

        assert seen == expected
