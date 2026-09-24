from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized
from temporalio.exceptions import ApplicationError

from posthog.models.comment import Comment

from products.conversations.backend.models.ticket import Status, Ticket
from products.conversations.backend.temporal.ticket_patterns.constants import (
    COLLECTION_BUDGET_SECONDS,
    COORDINATOR_INTERVAL_MINUTES,
    DETECTION_BATCH_BUDGET_SECONDS,
    DETECTION_BATCHES_PER_RUN,
    MAX_MESSAGE_CHARS,
    RUN_BUDGET_SECONDS,
    RUN_OVERHEAD_SECONDS,
)
from products.conversations.backend.temporal.ticket_patterns.coordinator import _collect_eligible_teams
from products.conversations.backend.temporal.ticket_patterns.detect import (
    _can_any_cluster_qualify,
    _detection_text,
    _load_candidates,
    _qualifying_clusters,
    _requester_key,
)
from products.conversations.backend.temporal.ticket_patterns.schemas import DetectionSettings

COORD_MODULE = "products.conversations.backend.temporal.ticket_patterns.coordinator"
ELIGIBILITY_MODULE = "products.conversations.backend.temporal.ticket_patterns.eligibility"
SCHEDULE_MODULE = "products.conversations.backend.temporal.ticket_patterns.schedule"

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


class _FakeQuerySet:
    """Enough of a queryset for the collector: it counts, slices and iterates."""

    def __init__(self, rows: list) -> None:
        self._rows = rows

    def count(self) -> int:
        return len(self._rows)

    def __iter__(self):
        return iter(self._rows)

    def __getitem__(self, item):
        result = self._rows[item]
        return _FakeQuerySet(result) if isinstance(item, slice) else result


def _queryset(mock_team_model, rows):
    mock_team_model.objects.filter.return_value.select_related.return_value.order_by.return_value = _FakeQuerySet(rows)


def _settings(min_tickets: int = 3, min_requesters: int = 3) -> DetectionSettings:
    return DetectionSettings(lookback_minutes=180, min_tickets=min_tickets, min_requesters=min_requesters)


def _requesters(*pairs: tuple[str, str]) -> dict[str, str]:
    return dict(pairs)


def test_everything_a_run_does_fits_inside_its_execution_timeout() -> None:
    # The schedule kills the run at the timeout. Sizing the batches to fill it and then adding
    # collection on top overruns silently, skipping the teams in the later batches.
    worst_case = (
        COLLECTION_BUDGET_SECONDS + DETECTION_BATCHES_PER_RUN * DETECTION_BATCH_BUDGET_SECONDS + RUN_OVERHEAD_SECONDS
    )

    assert worst_case <= RUN_BUDGET_SECONDS


@pytest.mark.asyncio
@pytest.mark.parametrize("already_exists", [False, True])
async def test_a_coordinator_run_cannot_outlive_its_own_interval(already_exists: bool) -> None:
    # Without a bound, one team whose detect activity sits out its retries holds the tick open
    # and the overlap policy drops the next ticks for every other team.
    from products.conversations.backend.temporal.ticket_patterns.schedule import (
        create_ticket_patterns_coordinator_schedule,
    )

    with (
        patch(f"{SCHEDULE_MODULE}.a_schedule_exists", return_value=already_exists),
        patch(f"{SCHEDULE_MODULE}.a_create_schedule") as create,
        patch(f"{SCHEDULE_MODULE}.a_update_schedule") as update,
    ):
        await create_ticket_patterns_coordinator_schedule(MagicMock())

    call = (update if already_exists else create).await_args
    assert call is not None
    schedule = call.args[2]
    interval = schedule.spec.intervals[0].every
    assert schedule.action.execution_timeout is not None
    assert schedule.action.execution_timeout < interval


class TestCollectEligibleTeams(SimpleTestCase):
    @parameterized.expand(
        [
            ("master_flag_off", {"master_flag": False}),
            ("toggle_off", {"ticket_patterns_enabled": False}),
            ("toggle_stored_as_string_false", {"ticket_patterns_enabled": "false"}),
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
                "unhashable_ids_are_skipped_not_fatal",
                [{"topic": "login", "summary": "", "ticket_ids": [["t1"], {"id": "t2"}, "t1", "t2", "t3"]}],
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


class TestRequesterKey(SimpleTestCase):
    @parameterized.expand(
        [
            ("organization_wins", {"organization_id": "acme", "distinct_id": "someone"}, "org:acme"),
            ("then_the_person", {"organization_id": "", "distinct_id": "someone"}, "person:someone"),
            (
                "then_a_trait",
                {"organization_id": "", "distinct_id": "", "anonymous_traits": {"name": "Robin"}},
                "name:Robin",
            ),
        ]
    )
    def test_identity_falls_through(self, _name, attrs, expected):
        ticket = MagicMock()
        ticket.organization_id = attrs.get("organization_id", "")
        ticket.distinct_id = attrs.get("distinct_id", "")
        ticket.anonymous_traits = attrs.get("anonymous_traits", {})
        ticket.email_from = attrs.get("email_from", "")

        assert _requester_key(ticket) == expected

    def test_unidentified_customers_do_not_collapse_into_one(self):
        # A Slack ticket whose author has no email stores an empty distinct_id. Keyed on that
        # alone every such customer counted as the same one, and a real spike never reached the
        # requester threshold.
        keys = set()
        for index in range(3):
            ticket = MagicMock()
            ticket.organization_id = ""
            ticket.distinct_id = ""
            ticket.anonymous_traits = {}
            ticket.email_from = ""
            ticket.id = f"ticket-{index}"
            keys.add(_requester_key(ticket))

        assert len(keys) == 3


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


class TestCanAnyClusterQualify(SimpleTestCase):
    # Every cluster the model returns is a subset of the candidates, so the whole set falling
    # short means no cluster can clear the thresholds. Getting this wrong either buys a sonnet
    # call whose answer must be discarded, or skips a spike that would have qualified.
    @parameterized.expand(
        [
            ("enough tickets and customers", ["a", "b", "c"], True),
            ("enough tickets from too few customers", ["a", "b", "d"], False),
            ("too few unreported tickets", ["a", "b"], False),
            ("nothing left unreported", [], False),
        ]
    )
    def test_the_thresholds_decide_before_the_model_is_asked(self, _name, fresh_ids, expected):
        requesters = {"a": "org:1", "b": "org:2", "c": "org:3", "d": "org:1"}

        assert _can_any_cluster_qualify(fresh_ids, requesters, _settings()) is expected


class TestDetectionText(SimpleTestCase):
    @staticmethod
    def _message(stop_reason: str):
        block = MagicMock()
        block.type = "text"
        block.text = '{"clusters": [{"topic": "checkout", "ticket_ids": ["a"'
        message = MagicMock()
        message.stop_reason = stop_reason
        message.content = [block]
        return message

    def test_a_response_cut_off_by_the_cap_is_refused_and_not_retried(self):
        # Truncated JSON is still JSON-shaped, so without this it reaches the parser as
        # "was not JSON" and two more identical requests are sent.
        with self.assertRaises(ApplicationError) as caught:
            _detection_text(self._message("max_tokens"))

        assert caught.exception.non_retryable
        assert "token cap" in str(caught.exception)

    def test_a_complete_response_is_returned(self):
        assert _detection_text(self._message("end_turn")).startswith('{"clusters"')


class TestRunTicketPatternsCommand(BaseTest):
    @parameterized.expand(
        [
            ("support off", False, True, True, "Support is off"),
            ("detection off", True, False, True, "Ticket spike detection is off"),
            ("no ai approval", True, True, False, "has not approved AI data processing"),
        ]
    )
    def test_a_closed_gate_is_named_rather_than_reported_as_no_spikes(
        self, _name, conversations_enabled, detection_enabled, ai_approved, expected
    ):
        # Without the check the command reaches detection, which rejects the team and returns
        # nothing, so the run prints "No spikes found" for a team it never scanned.
        self.team.conversations_enabled = conversations_enabled
        self.team.conversations_settings = {"ticket_patterns_enabled": detection_enabled}
        self.team.save()
        self.organization.is_ai_data_processing_approved = ai_approved
        self.organization.save()

        with self.assertRaises(CommandError) as caught:
            call_command("run_ticket_patterns", f"--team-id={self.team.id}", "--dry-run")

        assert expected in str(caught.exception)


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

    def test_a_long_opening_message_still_fills_the_model_budget(self):
        # The query fetches a capped prefix instead of the whole body, so the cut has to land
        # where it did when the whole body was loaded. Too small a window silently starves the
        # model of text it used to get.
        ticket = self._ticket_with_opener(
            subject="Cannot log in",
            author_type="customer",
            distinct_id="someone@example.com",
        )
        Comment.objects.filter(item_id=str(ticket.id)).update(content="x" * (MAX_MESSAGE_CHARS * 5))

        candidates, _ = _load_candidates(self.team.id, _settings())

        assert [c.message for c in candidates] == ["x" * MAX_MESSAGE_CHARS]

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

    @parameterized.expand([("slack", "slack_user_id"), ("teams", "teams_user_id")])
    def test_chat_customers_with_one_display_name_count_separately(self, channel, user_id_field):
        # A chat author with no email is stored by display name only, and every failed profile
        # lookup stores "Unknown". Keyed on that, these customers counted as one and a real spike
        # never reached the requester threshold.
        tickets = []
        for user_id in ("author-1", "author-2"):
            ticket = Ticket.objects.create_with_number(
                team=self.team,
                channel_source=channel,
                widget_session_id="",
                distinct_id="",
                anonymous_traits={"name": "Unknown"},
                status=Status.OPEN,
            )
            Comment.objects.create(
                team=self.team,
                scope="conversations_ticket",
                item_id=str(ticket.id),
                content="Replays do not load",
                item_context={"author_type": "customer", "is_private": False, user_id_field: user_id},
            )
            tickets.append(ticket)

        _, requesters = _load_candidates(self.team.id, _settings())

        assert len({requesters[str(ticket.id)] for ticket in tickets}) == 2
