from __future__ import annotations

import uuid

from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase

from parameterized import parameterized

from products.conversations.backend.temporal.ticket_patterns.coordinator import _collect_eligible_teams
from products.conversations.backend.temporal.ticket_patterns.detect import _qualifying_clusters
from products.conversations.backend.temporal.ticket_patterns.schemas import DetectionSettings

COORD_MODULE = "products.conversations.backend.temporal.ticket_patterns.coordinator"

TEST_TEAM_UUID = uuid.UUID("11111111-1111-4111-8111-111111111111")
TEST_ORG_UUID = uuid.UUID("22222222-2222-4222-8222-222222222222")


def _make_team(*, ticket_patterns_enabled: bool = True, ai_data_processing_approved: bool = True):
    org = MagicMock()
    org.is_ai_data_processing_approved = ai_data_processing_approved
    team = MagicMock()
    team.id = 7
    team.uuid = TEST_TEAM_UUID
    team.organization_id = TEST_ORG_UUID
    team.organization = org
    team.conversations_settings = {"ticket_patterns_enabled": ticket_patterns_enabled}
    return team


def _settings(min_tickets: int = 3, min_requesters: int = 3) -> DetectionSettings:
    return DetectionSettings(lookback_minutes=180, min_tickets=min_tickets, min_requesters=min_requesters)


def _requesters(*pairs: tuple[str, str]) -> dict[str, str]:
    return dict(pairs)


class TestCollectEligibleTeams(SimpleTestCase):
    @parameterized.expand(
        [
            ("master_flag_off", {"master_flag": False}),
            ("toggle_off", {"ticket_patterns_enabled": False}),
            ("ai_data_processing_not_approved", {"ai_data_processing_approved": False}),
        ]
    )
    @patch(f"{COORD_MODULE}._is_master_flag_enabled")
    @patch(f"{COORD_MODULE}.Team")
    def test_gate_blocks(self, _name, overrides, mock_team_model, mock_master_flag):
        # The queryset filters on the toggle, so a team with it off never reaches the loop.
        team = _make_team(ai_data_processing_approved=overrides.get("ai_data_processing_approved", True))
        rows = [] if overrides.get("ticket_patterns_enabled", True) is False else [team]
        mock_team_model.objects.filter.return_value.select_related.return_value = rows
        mock_master_flag.return_value = overrides.get("master_flag", True)

        assert _collect_eligible_teams() == []

    @patch(f"{COORD_MODULE}._is_master_flag_enabled", return_value=True)
    @patch(f"{COORD_MODULE}.Team")
    def test_opted_in_team_is_collected_with_its_thresholds(self, mock_team_model, _mock_master_flag):
        team = _make_team()
        team.conversations_settings["ticket_patterns_min_tickets"] = 8
        mock_team_model.objects.filter.return_value.select_related.return_value = [team]

        collected = _collect_eligible_teams()

        assert len(collected) == 1
        assert collected[0].team_id == 7
        assert collected[0].settings.min_tickets == 8


class TestQualifyingClusters(SimpleTestCase):
    def setUp(self) -> None:
        cache.clear()

    @parameterized.expand(
        [
            (
                "too_few_requesters",
                [{"topic": "login", "summary": "", "ticket_ids": ["t1", "t2", "t3"]}],
                _requesters(("t1", "org:a"), ("t2", "org:a"), ("t3", "org:a")),
                0,
            ),
            (
                "hallucinated_ids_drop_it_below_the_ticket_threshold",
                [{"topic": "login", "summary": "", "ticket_ids": ["t1", "t2", "nope"]}],
                _requesters(("t1", "org:a"), ("t2", "org:b")),
                0,
            ),
            (
                "repeated_ids_count_once",
                [{"topic": "login", "summary": "", "ticket_ids": ["t1", "t1", "t2", "t3"]}],
                _requesters(("t1", "org:a"), ("t2", "org:b"), ("t3", "org:c")),
                1,
            ),
            (
                "enough_tickets_from_enough_customers",
                [{"topic": "login", "summary": "cannot sign in", "ticket_ids": ["t1", "t2", "t3"]}],
                _requesters(("t1", "org:a"), ("t2", "org:b"), ("t3", "org:c")),
                1,
            ),
        ]
    )
    def test_thresholds(self, _name, raw_clusters, requesters, expected_count):
        clusters = _qualifying_clusters(raw_clusters, requesters, _settings(), team_id=7)

        assert len(clusters) == expected_count

    def test_a_ticket_belongs_to_one_cluster_only(self):
        raw_clusters = [
            {"topic": "login", "summary": "", "ticket_ids": ["t1", "t2", "t3"]},
            {"topic": "billing", "summary": "", "ticket_ids": ["t3", "t4", "t5"]},
        ]
        requesters = _requesters(("t1", "org:a"), ("t2", "org:b"), ("t3", "org:c"), ("t4", "org:d"), ("t5", "org:e"))

        clusters = _qualifying_clusters(raw_clusters, requesters, _settings(), team_id=7)

        assert len(clusters) == 1
        assert clusters[0].topic == "login"
        assert clusters[0].requester_count == 3


class TestDedupe(SimpleTestCase):
    def setUp(self) -> None:
        cache.clear()

    def test_a_spike_reports_once_then_again_only_when_new_tickets_arrive(self):
        from products.conversations.backend.temporal.ticket_patterns.dedupe import mark_reported

        raw = [{"topic": "login", "summary": "", "ticket_ids": ["t1", "t2", "t3"]}]
        requesters = _requesters(("t1", "org:a"), ("t2", "org:b"), ("t3", "org:c"))

        first = _qualifying_clusters(raw, requesters, _settings(), team_id=7)
        assert len(first) == 1
        mark_reported(7, first[0].ticket_ids)

        assert _qualifying_clusters(raw, requesters, _settings(), team_id=7) == []

        grown = [{"topic": "login", "summary": "", "ticket_ids": ["t1", "t2", "t3", "t4", "t5", "t6"]}]
        requesters.update({"t4": "org:d", "t5": "org:e", "t6": "org:f"})

        second = _qualifying_clusters(grown, requesters, _settings(), team_id=7)

        assert len(second) == 1
        assert second[0].ticket_ids == ["t4", "t5", "t6"]
