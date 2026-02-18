"""
Management command for seeding the property value Redis cache with a partial set of values.

The cache key includes event names when the UI is scoped to a specific event (e.g.
filtering properties for '$pageview' only). Pass --event-names to match the key the
API uses in that context. Check the exact key with inspect_property_value_cache --dump.

Workflow:
  1. Seed the cache (omit one value that exists in real data):
       python manage.py seed_property_value_cache \\
           --property-key product_key --values session_replay --team-id 1

     If the UI sends event names (visible in the network tab as event_name= params):
       python manage.py seed_property_value_cache \\
           --property-key product_key --values session_replay --team-id 1 \\
           --event-names '$pageview'

  2. Open the UI and select the property filter. You'll see session_replay with a
     loading spinner (refreshing=true). The background task queries ClickHouse.

  3. The frontend polls and the missing value appears with a "New" badge.

Requires Celery to be running so the background refresh task executes.
"""

import time

from django.core.management.base import BaseCommand, CommandError

from posthog.api.property_value_cache import _make_cache_key, cache_property_values, clear_refresh_cooldown

# Longer than a typical background task query to outlast any in-flight tasks
DEFAULT_WAIT_SECONDS = 15


class Command(BaseCommand):
    help = "Seed the property value Redis cache with a partial set of values for UI testing"

    def add_arguments(self, parser):
        parser.add_argument(
            "--team-id",
            type=int,
            help="Team ID (default: first team in the database)",
        )
        parser.add_argument(
            "--property-key",
            default="email",
            help="Property key to seed (default: email)",
        )
        parser.add_argument(
            "--property-type",
            default="event",
            choices=["event", "person"],
            help="Property type (default: event)",
        )
        parser.add_argument(
            "--values",
            default="alice@example.com,bob@example.com",
            help="Comma-separated values to store (default: alice@example.com,bob@example.com)",
        )
        parser.add_argument(
            "--event-names",
            default="",
            help=(
                "Comma-separated event names the UI includes in the request (e.g. '$pageview'). "
                "Check the network tab for event_name= params — omitting this when the UI sends "
                "event names will write to a different Redis key than the API reads from."
            ),
        )
        parser.add_argument(
            "--wait",
            action="store_true",
            help=(
                f"Wait {DEFAULT_WAIT_SECONDS}s before writing, so any in-flight Celery refresh tasks "
                "finish and can't overwrite the seeded values afterward."
            ),
        )

    def handle(self, *args, **options):
        from posthog.models.team.team import Team

        team_id = options["team_id"]
        if team_id is None:
            team = Team.objects.order_by("id").first()
            if team is None:
                raise CommandError("No teams found. Create a team first or pass --team-id.")
            team_id = team.pk
            self.stdout.write(f"No --team-id given, using team {team_id} ({team.name})")
        else:
            if not Team.objects.filter(pk=team_id).exists():
                raise CommandError(f"Team {team_id} not found.")

        property_key = options["property_key"]
        property_type = options["property_type"]
        raw_values = [v.strip() for v in options["values"].split(",") if v.strip()]
        event_names = [e.strip() for e in options["event_names"].split(",") if e.strip()] or None

        if not raw_values:
            raise CommandError("--values must contain at least one non-empty value.")

        if options["wait"]:
            self.stdout.write(f"Waiting {DEFAULT_WAIT_SECONDS}s for any in-flight background tasks to finish...")
            time.sleep(DEFAULT_WAIT_SECONDS)

        formatted_values = [{"name": v} for v in raw_values]

        cache_key = _make_cache_key(team_id, property_type, property_key, event_names=event_names)
        self.stdout.write(f"Writing to Redis key: {cache_key}")
        if event_names:
            self.stdout.write(f"  (event names: {event_names})")

        cache_property_values(
            team_id=team_id,
            property_type=property_type,
            property_key=property_key,
            values=formatted_values,
            event_names=event_names,
        )
        clear_refresh_cooldown(team_id, property_type, property_key, event_names=event_names)

        self.stdout.write(
            self.style.SUCCESS(
                f"Cached {len(formatted_values)} values for {property_type} property '{property_key}' "
                f"(team {team_id}): {', '.join(raw_values)}"
            )
        )
        self.stdout.write(
            "Cooldown cleared — the next API request will return refreshing=true and trigger a background refresh.\n"
            "Open the UI, select the property filter, and watch the missing values appear."
        )
