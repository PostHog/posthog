"""Run ticket pattern detection for one team without waiting for the schedule.

`--backtest N` replays the last N days in window-sized steps and prints what would have opened,
without writing anything. Use it to check the alert rate on a project before turning detection on.
"""

from __future__ import annotations

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
from products.conversations.backend.temporal.patterns.constants import BASELINE_SAMPLE_WINDOW_DAYS


class Command(BaseCommand):
    help = "Run ticket pattern detection or a baseline refresh for one team."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--refresh-baselines", action="store_true", help="Relearn topic baselines first")
        parser.add_argument("--backtest", type=int, metavar="DAYS", help="Replay the last DAYS days read-only")
        parser.add_argument("--min-requesters", type=int, help="Override the team setting for this run")
        parser.add_argument("--min-tickets", type=int, help="Override the team setting for this run")

    def handle(self, *args, **options) -> None:
        team = Team.objects.select_related("organization").filter(id=options["team_id"]).first()
        if team is None:
            raise CommandError(f"Team {options['team_id']} not found")
        now = timezone.now()

        if options["backtest"]:
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
        step = timedelta(minutes=settings.window_minutes)
        cursor = now - timedelta(days=days)
        # Candidates are deduped on fingerprint so a burst spanning several windows counts once, the
        # way the upsert would treat it in production.
        seen: dict[str, tuple[datetime, int, int]] = {}
        while cursor < now:
            texts = load_ticket_texts(team, since=cursor, until=cursor + step)
            for candidate in find_candidates(texts, settings, baselines):
                if candidate.fingerprint not in seen:
                    seen[candidate.fingerprint] = (cursor, candidate.ticket_count, candidate.requester_count)
            cursor += step

        self.stdout.write(
            f"{days} days, window {settings.window_minutes}m, min_requesters={settings.min_requesters}, "
            f"min_tickets={settings.min_tickets}, baselines={len(baselines)}"
        )
        self.stdout.write(
            self.style.SUCCESS(f"{len(seen)} patterns would have opened ({len(seen) / days:.2f} per day)")
        )
        for fingerprint, (when, tickets, requesters) in sorted(seen.items(), key=lambda kv: kv[1][0]):
            self.stdout.write(
                f"  {when:%Y-%m-%d %H:%M}  {tickets:>3} tickets / {requesters:>2} requesters  {fingerprint}"
            )
