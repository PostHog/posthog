"""
Stream live demo events continuously for local development.

Sends events through capture-rs so they appear in the livestream service.

Usage:
    python manage.py stream_live_events              # Run in foreground
    python manage.py stream_live_events &            # Run in background
    python manage.py stream_live_events --team-id 2  # Specific team
    python manage.py stream_live_events --rate 5     # 5 events per second
"""

import time
import random
import datetime as dt

from django.core.management.base import BaseCommand

from posthog.api.capture import capture_internal
from posthog.demo.products.hedgebox import HedgeboxMatrix
from posthog.models.team import Team


class Command(BaseCommand):
    help = "Stream live demo events continuously for local development"

    def add_arguments(self, parser):
        parser.add_argument("--team-id", type=int, help="Team ID to send events to")
        parser.add_argument("--rate", type=float, default=2.0, help="Events per second (default: 2)")
        parser.add_argument(
            "--clusters", type=int, default=20, help="Number of user clusters to simulate (default: 20)"
        )
        parser.add_argument("--no-loop", action="store_true", help="Stop after exhausting events instead of looping")

    def handle(self, *args, **options):
        team = self.get_team(options.get("team_id"))
        events = self.generate_events(n_clusters=options["clusters"])

        try:
            self.stream_events(team, events, rate=options["rate"], loop=not options["no_loop"])
        except KeyboardInterrupt:
            self.stdout.write("\nStopped.")

    def get_team(self, team_id: int | None) -> Team:
        if team_id:
            return Team.objects.get(pk=team_id)
        team = Team.objects.order_by("id").first()
        if not team:
            self.stderr.write("No team found. Run the app first to create a team.")
            raise SystemExit(1)
        return team

    def generate_events(self, n_clusters: int = 20, days_future: int = 1):
        self.stdout.write(f"Generating event pool with {n_clusters} clusters...")
        matrix = HedgeboxMatrix(
            seed=str(random.randint(0, 1000000)),
            now=dt.datetime.now(dt.UTC),
            days_past=1,
            days_future=days_future,
            n_clusters=n_clusters,
        )
        matrix.simulate()

        events = []
        for person in matrix.people:
            events.extend(person.future_events)

        random.shuffle(events)
        self.stdout.write(f"Generated {len(events)} events to stream")
        return events

    def stream_events(self, team: Team, events: list, rate: float, loop: bool):
        delay = 1.0 / rate if rate > 0 else 0
        event_index = 0
        total_sent = 0

        self.stdout.write(f"Streaming to team {team.id} ({team.name}) at ~{rate} events/sec")
        self.stdout.write("Press Ctrl+C to stop\n")

        while True:
            if event_index >= len(events):
                if loop:
                    self.stdout.write(f"\nLooping... (sent {total_sent} events so far)")
                    random.shuffle(events)
                    event_index = 0
                else:
                    self.stdout.write(f"\nDone. Sent {total_sent} events.")
                    break

            sim_event = events[event_index]
            event_index += 1

            try:
                response = capture_internal(
                    token=team.api_token,
                    event_name=sim_event.event,
                    event_source="stream_live_events",
                    distinct_id=sim_event.distinct_id,
                    timestamp=dt.datetime.now(dt.UTC),
                    properties=sim_event.properties,
                )
                response.raise_for_status()
                total_sent += 1

                if total_sent % 100 == 0:
                    self.stdout.write(f"  Sent {total_sent} events...", ending="\r")

            except Exception as e:
                self.stderr.write(f"Error sending event: {e}")

            if delay > 0:
                time.sleep(delay)
