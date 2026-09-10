"""Run ticket pattern detection for one team without waiting for the schedule.

`--backtest N` replays the last N days on the same cadence the schedule runs, evaluating the
preceding window at every coordinator tick, and prints what would have opened without writing
anything. Use it to check the alert rate on a project before turning detection on.
"""

from __future__ import annotations

from argparse import ArgumentTypeError
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from posthog.models import Team

from products.conversations.backend.models import TicketTopicBaseline
from products.conversations.backend.pattern_detection import (
    PatternSettings,
    find_candidates,
    load_ticket_texts,
    refresh_baselines,
    run_detection,
)
from products.conversations.backend.temporal.patterns.constants import (
    BASELINE_SAMPLE_WINDOW_DAYS,
    COORDINATOR_INTERVAL_MINUTES,
)
from products.conversations.backend.temporal.patterns.coordinator import floor_to_tick


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise ArgumentTypeError(f"must be a positive integer, got {value}")
    return parsed


class Command(BaseCommand):
    help = "Run ticket pattern detection or a baseline refresh for one team."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--refresh-baselines", action="store_true", help="Relearn topic baselines first")
        parser.add_argument(
            "--backtest", type=_positive_int, metavar="DAYS", help="Replay the last DAYS days read-only"
        )
        parser.add_argument(
            "--min-requesters", type=_positive_int, help="Override the team setting. Only applies to --backtest"
        )
        parser.add_argument(
            "--min-tickets", type=_positive_int, help="Override the team setting. Only applies to --backtest"
        )

    def handle(self, *args, **options) -> None:
        overrides = [name for name in ("min_requesters", "min_tickets") if options[name] is not None]
        if overrides and options["backtest"] is None:
            flags = ", ".join(f"--{name.replace('_', '-')}" for name in overrides)
            raise CommandError(f"{flags} only works with --backtest. A live run uses the team's own settings.")

        team = Team.objects.select_related("organization").filter(id=options["team_id"]).first()
        if team is None:
            raise CommandError(f"Team {options['team_id']} not found")
        now = timezone.now()

        if options["backtest"] is not None:
            self._backtest(team, now=now, days=options["backtest"], options=options)
            return

        if options["refresh_baselines"]:
            count = refresh_baselines(team, now=now, sample_window_days=BASELINE_SAMPLE_WINDOW_DAYS)
            self.stdout.write(f"Refreshed {count} topic baselines")

        outcome = run_detection(team, now=now)
        self.stdout.write(
            self.style.SUCCESS(
                f"opened={len(outcome.opened)} updated={len(outcome.updated)} "
                f"suppressed={len(outcome.suppressed)} auto_resolved={len(outcome.auto_resolved)}"
            )
        )

    def _backtest(self, team: Team, *, now: datetime, days: int, options: dict) -> None:
        settings = PatternSettings.from_team(team)
        if options.get("min_requesters"):
            settings = PatternSettings(
                min_requesters=options["min_requesters"],
                min_tickets=settings.min_tickets,
                window_minutes=settings.window_minutes,
            )
        if options.get("min_tickets"):
            settings = PatternSettings(
                min_requesters=settings.min_requesters,
                min_tickets=options["min_tickets"],
                window_minutes=settings.window_minutes,
            )
        baselines = {b.topic: b for b in TicketTopicBaseline.objects.for_team(team.id)}
        # Production evaluates the preceding window on every coordinator tick, so the replay walks
        # the same overlapping windows. Stepping a window at a time instead would split a burst
        # that straddles a boundary, and report nothing for the marginal cases that set the rate.
        window = timedelta(minutes=settings.window_minutes)
        step = timedelta(minutes=COORDINATOR_INTERVAL_MINUTES)
        cursor = floor_to_tick(now - timedelta(days=days))
        # Candidates are deduped on fingerprint so a burst spanning several windows counts once, the
        # way the upsert would treat it in production.
        seen: dict[str, tuple[datetime, int, int]] = {}
        while cursor < now:
            texts = load_ticket_texts(team, since=cursor - window, until=cursor)
            for candidate in find_candidates(texts, settings, baselines):
                if candidate.fingerprint not in seen:
                    seen[candidate.fingerprint] = (cursor, candidate.ticket_count, candidate.requester_count)
            cursor += step

        self.stdout.write(
            f"{days} days, {settings.window_minutes}m window every {COORDINATOR_INTERVAL_MINUTES}m, "
            f"min_requesters={settings.min_requesters}, min_tickets={settings.min_tickets}, "
            f"baselines={len(baselines)}"
        )
        self.stdout.write(
            self.style.SUCCESS(f"{len(seen)} patterns would have opened ({len(seen) / days:.2f} per day)")
        )
        for fingerprint, (when, tickets, requesters) in sorted(seen.items(), key=lambda kv: kv[1][0]):
            self.stdout.write(
                f"  {when:%Y-%m-%d %H:%M}  {tickets:>3} tickets / {requesters:>2} requesters  {fingerprint}"
            )
