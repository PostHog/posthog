from __future__ import annotations

from datetime import timedelta
from io import StringIO

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.models import Team
from posthog.models.comment import Comment
from posthog.models.scoping import team_scope

from products.conversations.backend.models import (
    Ticket,
    TicketPattern,
    TicketPatternEvidence,
    TicketPatternStatus,
    TicketTopicBaseline,
)
from products.conversations.backend.pattern_detection import (
    DEFAULT_MIN_REQUESTERS,
    MAX_TOPIC_LENGTH,
    PatternSettings,
    TopicCandidate,
    load_ticket_texts,
    refresh_baselines,
    required_requesters,
    run_detection,
)


class TestRequiredRequesters(SimpleTestCase):
    @parameterized.expand(
        [
            ("no_baseline", PatternSettings(), None, DEFAULT_MIN_REQUESTERS),
            (
                "recurring_topic_raises_bar",
                PatternSettings(),
                TicketTopicBaseline(distinct_days_seen=5),
                DEFAULT_MIN_REQUESTERS + 2,
            ),
            (
                "rare_topic_spiking_lowers_bar",
                PatternSettings(),
                TicketTopicBaseline(mean_per_hour=0.1, distinct_days_seen=2),
                3,
            ),
            (
                "dismissals_raise_bar",
                PatternSettings(),
                TicketTopicBaseline(dismiss_count=2),
                DEFAULT_MIN_REQUESTERS + 2,
            ),
            (
                "dismissals_cap_at_three",
                PatternSettings(),
                TicketTopicBaseline(dismiss_count=9),
                DEFAULT_MIN_REQUESTERS + 3,
            ),
            (
                "confirmations_lower_bar",
                PatternSettings(),
                TicketTopicBaseline(confirm_count=2),
                DEFAULT_MIN_REQUESTERS - 2,
            ),
            ("never_below_floor", PatternSettings(), TicketTopicBaseline(confirm_count=5, mean_per_hour=0.1), 3),
            # Ten tickets a day is normal for the topic, so a day-long window is not a spike.
            (
                "wide_window_scales_the_spike_bar_up",
                PatternSettings(window_minutes=1440),
                TicketTopicBaseline(mean_per_hour=0.1, distinct_days_seen=2),
                DEFAULT_MIN_REQUESTERS,
            ),
            # Two an hour is normal, so ten in a quarter hour is a spike.
            (
                "short_window_scales_the_spike_bar_down",
                PatternSettings(window_minutes=15),
                TicketTopicBaseline(mean_per_hour=8.0, distinct_days_seen=2),
                DEFAULT_MIN_REQUESTERS - 2,
            ),
        ]
    )
    def test_bar_moves_with_baseline(self, _name, settings, baseline, expected):
        assert required_requesters(settings, baseline, observed_tickets=10) == expected


class TestFingerprintWidth(SimpleTestCase):
    def test_widest_topic_still_fits_the_fingerprint_column(self):
        widest = TopicCandidate(
            topic="a" * MAX_TOPIC_LENGTH,
            ticket_ids=(),
            requester_count=0,
            first_ticket_at=timezone.now(),
        )

        assert len(widest.fingerprint) <= TicketPattern._meta.get_field("fingerprint").max_length


class TestRunDetection(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.now = timezone.now()
        self._number = 0

    def _ticket(self, subject: str, sender: str, *, team: Team | None = None, created_at=None) -> Ticket:
        self._number += 1
        ticket = Ticket.objects.create(
            team=team or self.team,
            ticket_number=self._number,
            channel_source="email",
            email_subject=subject,
            email_from=sender,
        )
        Ticket.objects.filter(id=ticket.id).update(created_at=created_at or self.now - timedelta(minutes=5))
        return ticket

    def _burst(self, subject: str, *, requesters: int, tickets: int, team: Team | None = None) -> list[Ticket]:
        return [self._ticket(subject, f"user{i}@company{i % requesters}.example", team=team) for i in range(tickets)]

    def _ticket_with_comments(self, *comments: tuple[str, dict | None]) -> Ticket:
        self._number += 1
        ticket = Ticket.objects.create(team=self.team, ticket_number=self._number, channel_source="slack")
        Ticket.objects.filter(id=ticket.id).update(created_at=self.now - timedelta(minutes=5))
        for content, item_context in comments:
            Comment.objects.create(
                team=self.team,
                scope="conversations_ticket",
                item_id=str(ticket.id),
                content=content,
                item_context=item_context,
            )
        return ticket

    def _chat_ticket(self, message: str, *, slack_user_id: str) -> Ticket:
        # Slack and Teams store no email and an empty distinct id when the platform withholds one,
        # so the sender is only knowable from the first comment.
        self._number += 1
        ticket = Ticket.objects.create(team=self.team, ticket_number=self._number, channel_source="slack")
        Ticket.objects.filter(id=ticket.id).update(created_at=self.now - timedelta(minutes=5))
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content=message,
            item_context={"author_type": "customer", "is_private": False, "slack_user_id": slack_user_id},
        )
        return ticket

    @parameterized.expand(
        [
            ("one_requester_many_tickets", 1, 10, 0),
            ("enough_requesters", 5, 5, 1),
            ("requesters_below_bar", 4, 8, 0),
        ]
    )
    def test_requester_diversity_is_the_guard(self, _name, requesters, tickets, expected_patterns):
        self._burst("Cannot login to the dashboard", requesters=requesters, tickets=tickets)

        outcome = run_detection(self.team, now=self.now)

        assert len(outcome.opened) == expected_patterns
        assert TicketPattern.objects.for_team(self.team.id).count() == expected_patterns

    def test_one_burst_opens_one_pattern_not_one_per_overlapping_topic(self):
        self._burst("Login broken after password reset", requesters=6, tickets=6)

        outcome = run_detection(self.team, now=self.now)

        assert len(outcome.opened) == 1
        pattern = TicketPattern.objects.for_team(self.team.id).get()
        assert pattern.ticket_count == 6
        assert pattern.requester_count == 6
        assert TicketPatternEvidence.objects.for_team(self.team.id).filter(pattern=pattern).count() == 6

    @parameterized.expand(
        [
            ("still_open", TicketPatternStatus.OPEN),
            ("confirmed_by_a_human", TicketPatternStatus.CONFIRMED),
        ]
    )
    def test_second_tick_updates_the_active_pattern(self, _name, status):
        self._burst("Cannot login to the dashboard", requesters=5, tickets=5)
        first = run_detection(self.team, now=self.now)
        TicketPattern.objects.for_team(self.team.id).update(status=status)
        self._burst("Cannot login to the dashboard", requesters=5, tickets=3)

        second = run_detection(self.team, now=self.now + timedelta(minutes=15))

        assert len(first.opened) == 1
        assert second.opened == ()
        assert second.updated == first.opened
        pattern = TicketPattern.objects.for_team(self.team.id).get()
        assert pattern.status == status
        assert pattern.ticket_count == 8
        assert pattern.peak_ticket_count == 8

    def test_a_tick_that_loses_the_race_updates_the_winning_pattern(self):
        self._burst("Cannot login to the dashboard", requesters=5, tickets=5)
        first = run_detection(self.team, now=self.now)
        self._burst("Cannot login to the dashboard", requesters=5, tickets=3)

        real_for_team = TicketPattern.objects.for_team
        lookups: list[int] = []

        def blind_on_the_first_lookup(team_id: int):
            # Concurrency cannot be staged from one connection, so this stands in for a tick that
            # looked before the winner committed: it finds no pattern and its insert then loses to
            # the partial unique constraint.
            lookups.append(team_id)
            return real_for_team(team_id).none() if len(lookups) == 1 else real_for_team(team_id)

        with patch.object(TicketPattern.objects, "for_team", blind_on_the_first_lookup):
            second = run_detection(self.team, now=self.now + timedelta(minutes=15))

        assert second.opened == ()
        assert second.updated == first.opened
        assert TicketPattern.objects.for_team(self.team.id).count() == 1

    def test_a_confirmed_pattern_stops_blocking_once_its_topic_goes_quiet(self):
        self._burst("Cannot login to the dashboard", requesters=5, tickets=5)
        first = run_detection(self.team, now=self.now)
        TicketPattern.objects.for_team(self.team.id).update(status=TicketPatternStatus.CONFIRMED)

        later = self.now + timedelta(hours=4)
        for i in range(5):
            self._ticket(
                "Cannot login to the dashboard",
                f"later{i}@company{i}.example",
                created_at=later - timedelta(minutes=5),
            )
        second = run_detection(self.team, now=later)

        assert len(second.opened) == 1
        assert second.opened != first.opened
        assert TicketPattern.objects.for_team(self.team.id).count() == 2

    def test_dismissal_suppresses_until_volume_doubles(self):
        self._burst("Cannot login to the dashboard", requesters=5, tickets=5)
        run_detection(self.team, now=self.now)
        TicketPattern.objects.for_team(self.team.id).update(
            status=TicketPatternStatus.DISMISSED, resolved_at=self.now + timedelta(minutes=1)
        )

        still_quiet = run_detection(self.team, now=self.now + timedelta(minutes=30))
        assert still_quiet.opened == ()
        assert still_quiet.suppressed != ()

        self._burst("Cannot login to the dashboard", requesters=5, tickets=5)
        escalated = run_detection(self.team, now=self.now + timedelta(minutes=45))
        assert len(escalated.opened) == 1
        assert TicketPattern.objects.for_team(self.team.id).filter(status=TicketPatternStatus.OPEN).count() == 1

    def test_tickets_outside_the_window_and_other_teams_do_not_count(self):
        other_team = Team.objects.create(organization=self.organization)
        self._burst("Cannot login to the dashboard", requesters=4, tickets=4)
        self._ticket("Cannot login to the dashboard", "old@company9.example", created_at=self.now - timedelta(hours=3))
        self._ticket("Cannot login to the dashboard", "other@company8.example", team=other_team)

        outcome = run_detection(self.team, now=self.now)

        assert outcome.opened == ()

    @parameterized.expand(
        [
            ("support_wrote_first", [("staff note", {"author_type": "support"})]),
            ("first_is_private", [("internal", {"author_type": "customer", "is_private": True})]),
            ("first_is_empty", [("", {"author_type": "customer"})]),
        ]
    )
    def test_the_ticket_text_is_the_first_public_customer_message(self, _name, skipped):
        self._ticket_with_comments(*skipped, ("cannot login", {"author_type": "customer"}))

        texts = load_ticket_texts(self.team, since=self.now - timedelta(hours=1), until=self.now)

        assert [t.text for t in texts] == ["cannot login"]

    @parameterized.expand([("no_context", None), ("no_author_type", {}), ("empty_author_type", {"is_private": False})])
    def test_a_message_with_no_author_counts_as_the_customer(self, _name, item_context):
        self._ticket_with_comments(("cannot login", item_context), ("later reply", {"author_type": "customer"}))

        texts = load_ticket_texts(self.team, since=self.now - timedelta(hours=1), until=self.now)

        assert [t.text for t in texts] == ["cannot login"]

    @parameterized.expand(
        [
            ("unidentified_senders", ["", "", "", "", "", ""], 0),
            ("distinct_platform_users", ["U1", "U2", "U3", "U4", "U5"], 1),
        ]
    )
    def test_chat_tickets_count_requesters_by_platform_user(self, _name, slack_user_ids, expected_patterns):
        for slack_user_id in slack_user_ids:
            self._chat_ticket("Cannot login to the dashboard", slack_user_id=slack_user_id)

        outcome = run_detection(self.team, now=self.now)

        assert len(outcome.opened) == expected_patterns

    def test_backtest_reports_a_burst_that_straddles_a_window_boundary(self):
        # Half the burst each side of the hour mark a window-at-a-time replay would step on.
        for i in range(6):
            self._ticket(
                "Cannot login to the dashboard",
                f"user{i}@company{i}.example",
                created_at=self.now - timedelta(minutes=63 if i < 3 else 57),
            )

        out = StringIO()
        call_command("run_ticket_pattern_detection", "--team-id", str(self.team.id), "--backtest", "1", stdout=out)

        assert "1 patterns would have opened" in out.getvalue()

    def test_backtest_counts_a_topic_that_flares_again_after_the_quiet_interval(self):
        # Two bursts either side of the two quiet windows that auto-resolve the first pattern.
        for minutes_ago in (300, 60):
            for i in range(5):
                self._ticket(
                    "Cannot login to the dashboard",
                    f"user{i}@company{i}.example",
                    created_at=self.now - timedelta(minutes=minutes_ago),
                )

        out = StringIO()
        call_command("run_ticket_pattern_detection", "--team-id", str(self.team.id), "--backtest", "1", stdout=out)

        assert "2 patterns would have opened" in out.getvalue()

    @parameterized.expand([("zero", "0"), ("negative", "-5")])
    def test_command_rejects_a_backtest_that_is_not_a_positive_day_count(self, _name, days):
        self._burst("Cannot login to the dashboard", requesters=5, tickets=5)

        with self.assertRaises(CommandError):
            call_command("run_ticket_pattern_detection", "--team-id", str(self.team.id), "--backtest", days)

        assert TicketPattern.objects.for_team(self.team.id).count() == 0

    @parameterized.expand([("requesters", "--min-requesters"), ("tickets", "--min-tickets")])
    def test_command_rejects_a_threshold_override_outside_a_backtest(self, _name, flag):
        self._burst("Cannot login to the dashboard", requesters=5, tickets=5)

        with self.assertRaises(CommandError):
            call_command("run_ticket_pattern_detection", "--team-id", str(self.team.id), flag, "3")

        assert TicketPattern.objects.for_team(self.team.id).count() == 0

    def test_baseline_refresh_relearns_a_topic_that_only_survives_on_feedback(self):
        # The delete spares a topic with feedback, so nothing else would ever revisit its rate.
        with team_scope(self.team.id):
            TicketTopicBaseline.objects.create(
                team=self.team,
                topic="login",
                mean_per_hour=4.0,
                spread=2.0,
                distinct_days_seen=9,
                dismiss_count=1,
                refreshed_at=self.now - timedelta(days=1),
            )

        refresh_baselines(self.team, now=self.now, sample_window_days=30)

        baseline = TicketTopicBaseline.objects.for_team(self.team.id).get(topic="login")
        assert baseline.dismiss_count == 1
        assert baseline.mean_per_hour == 0.0
        assert baseline.distinct_days_seen == 0

    def test_quiet_pattern_auto_resolves(self):
        self._burst("Cannot login to the dashboard", requesters=5, tickets=5)
        run_detection(self.team, now=self.now)

        outcome = run_detection(self.team, now=self.now + timedelta(hours=3))

        pattern = TicketPattern.objects.for_team(self.team.id).get()
        assert outcome.auto_resolved == (pattern.id,)
        assert pattern.status == TicketPatternStatus.RESOLVED
        assert pattern.evidence["auto_resolved"] is True
