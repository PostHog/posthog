from __future__ import annotations

import uuid
from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.models.comment import Comment

from products.conversations.backend.models.ticket import Status, Ticket
from products.conversations.backend.temporal.ticket_patterns.constants import COORDINATOR_INTERVAL_MINUTES
from products.conversations.backend.temporal.ticket_patterns.coordinator import _collect_eligible_teams
from products.conversations.backend.temporal.ticket_patterns.detect import _load_candidates, _qualifying_clusters
from products.conversations.backend.temporal.ticket_patterns.schemas import DetectionSettings

COORD_MODULE = "products.conversations.backend.temporal.ticket_patterns.coordinator"
ELIGIBILITY_MODULE = "products.conversations.backend.temporal.ticket_patterns.eligibility"

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
    team.conversations_enabled = True
    team.conversations_settings = {"ticket_patterns_enabled": ticket_patterns_enabled}
    return team


def _queryset(mock_team_model, rows):
    mock_team_model.objects.filter.return_value.select_related.return_value.order_by.return_value = rows


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
            ("conversations_disabled", {"conversations_enabled": False}),
        ]
    )
    @patch(f"{ELIGIBILITY_MODULE}.is_master_flag_enabled")
    @patch(f"{COORD_MODULE}.Team")
    def test_gate_blocks(self, _name, overrides, mock_team_model, mock_master_flag):
        team = _make_team(
            ticket_patterns_enabled=overrides.get("ticket_patterns_enabled", True),
            ai_data_processing_approved=overrides.get("ai_data_processing_approved", True),
        )
        team.conversations_enabled = overrides.get("conversations_enabled", True)
        _queryset(mock_team_model, [team])
        mock_master_flag.return_value = overrides.get("master_flag", True)

        assert _collect_eligible_teams() == []

    @patch(f"{ELIGIBILITY_MODULE}.is_master_flag_enabled", return_value=True)
    @patch(f"{COORD_MODULE}.Team")
    def test_opted_in_team_is_collected_with_its_thresholds(self, mock_team_model, _mock_master_flag):
        team = _make_team()
        team.conversations_settings["ticket_patterns_min_tickets"] = 8
        _queryset(mock_team_model, [team])

        collected = _collect_eligible_teams()

        assert len(collected) == 1
        assert collected[0].team_id == 7
        assert collected[0].settings.min_tickets == 8

    @patch(f"{ELIGIBILITY_MODULE}.is_master_flag_enabled", return_value=True)
    @patch(f"{COORD_MODULE}.MAX_TEAMS_PER_RUN", 2)
    @patch(f"{COORD_MODULE}.Team")
    def test_every_team_is_reached_across_consecutive_ticks(self, mock_team_model, _mock_master_flag):
        teams = []
        for team_id in (1, 2, 3):
            team = _make_team()
            team.id = team_id
            teams.append(team)
        _queryset(mock_team_model, teams)

        seen: set[int] = set()
        for tick in range(3):
            with patch(f"{COORD_MODULE}.timezone") as mock_timezone:
                mock_timezone.now.return_value.timestamp.return_value = tick * COORDINATOR_INTERVAL_MINUTES * 60
                seen.update(item.team_id for item in _collect_eligible_teams())

        assert seen == {1, 2, 3}


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


class TestRecentSpikes(SimpleTestCase):
    def setUp(self) -> None:
        cache.clear()

    def test_newest_first_and_capped(self):
        from products.conversations.backend.temporal.ticket_patterns.recent import (
            MAX_RECENT_SPIKES,
            recent_spikes,
            record_spike,
        )

        for index in range(MAX_RECENT_SPIKES + 3):
            record_spike(7, {"topic": f"spike-{index}", "detected_at": timezone.now().isoformat()})

        stored = recent_spikes(7)

        assert len(stored) == MAX_RECENT_SPIKES
        assert stored[0]["topic"] == f"spike-{MAX_RECENT_SPIKES + 2}"

    def test_spikes_are_per_team(self):
        from products.conversations.backend.temporal.ticket_patterns.recent import recent_spikes, record_spike

        record_spike(7, {"topic": "only-team-7", "detected_at": timezone.now().isoformat()})

        assert recent_spikes(8) == []

    @parameterized.expand(
        [
            ("a day and an hour old", 25 * 60 * 60, False),
            ("an hour old", 60 * 60, True),
            ("undateable", None, False),
        ]
    )
    def test_only_spikes_from_the_last_day_are_served(self, _name, age_seconds, expected):
        from products.conversations.backend.temporal.ticket_patterns.recent import recent_spikes, record_spike

        spike = {"topic": "older"}
        if age_seconds is not None:
            spike["detected_at"] = (timezone.now() - timedelta(seconds=age_seconds)).isoformat()
        record_spike(7, spike)

        # A later write rewrites the one key with a fresh TTL, so without the cutoff the stale
        # entry would be carried forward and served as recent for another day.
        record_spike(7, {"topic": "newer", "detected_at": timezone.now().isoformat()})

        topics = [s["topic"] for s in recent_spikes(7)]
        assert ("older" in topics) is expected
        assert "newer" in topics


class TestLoadCandidates(BaseTest):
    def _ticket_with_opener(self, *, subject: str, author_type: str, distinct_id: str) -> Ticket:
        ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source="email",
            widget_session_id="",
            distinct_id=distinct_id,
            email_from=distinct_id,
            email_subject=subject,
            status=Status.OPEN,
        )
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content=f"{subject} body",
            item_context={"author_type": author_type, "is_private": False},
        )
        return ticket

    @parameterized.expand(
        [
            ("customer", "customer", True),
            ("outbound mail an agent composed", "human", False),
            ("a teammate's post in a shared channel", "support", False),
            ("unlabelled", None, False),
        ]
    )
    def test_only_a_customer_authored_opener_makes_a_candidate(self, _name, author_type, expected):
        # An outbound batch carries one subject to many recipients, so without this a team's own
        # campaign clears the thresholds and is reported back to them as a customer spike.
        ticket = self._ticket_with_opener(
            subject="Scheduled maintenance",
            author_type=author_type,
            distinct_id="someone@example.com",
        )
        if author_type is None:
            Comment.objects.filter(item_id=str(ticket.id)).update(item_context={"is_private": False})

        candidates, requesters = _load_candidates(self.team.id, _settings())

        assert [c.ticket_id for c in candidates] == ([str(ticket.id)] if expected else [])
        assert (str(ticket.id) in requesters) is expected

    def test_a_customer_opener_with_no_privacy_flag_still_counts(self):
        # A bare exclude() reads a missing key as SQL NULL and drops the row, which is why the
        # product keeps one shared predicate for this. Older rows carry no key.
        ticket = self._ticket_with_opener(
            subject="Cannot log in",
            author_type="customer",
            distinct_id="someone@example.com",
        )
        Comment.objects.filter(item_id=str(ticket.id)).update(item_context={"author_type": "customer"})

        candidates, _ = _load_candidates(self.team.id, _settings())

        assert [c.ticket_id for c in candidates] == [str(ticket.id)]

    def test_a_deleted_message_is_not_sent_to_the_model(self):
        # Ticket messages are soft-deletable through the generic comments API, and deleted text
        # must not reach an LLM payload.
        ticket = self._ticket_with_opener(
            subject="Cannot log in",
            author_type="customer",
            distinct_id="someone@example.com",
        )
        Comment.objects.filter(item_id=str(ticket.id)).update(deleted=True)

        candidates, _ = _load_candidates(self.team.id, _settings())

        assert candidates == []

    def test_a_team_reply_does_not_stand_in_for_a_missing_customer_opener(self):
        # last_message_text holds whatever was said last, so a reply on a team-started ticket
        # used to put that ticket back into the candidate set.
        ticket = self._ticket_with_opener(
            subject="Scheduled maintenance",
            author_type="human",
            distinct_id="someone@example.com",
        )
        ticket.last_message_text = "We are still working on it."
        ticket.save(update_fields=["last_message_text"])

        candidates, _ = _load_candidates(self.team.id, _settings())

        assert candidates == []
