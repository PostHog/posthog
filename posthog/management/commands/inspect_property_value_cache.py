"""Management command to inspect Redis property value cache entries for debugging."""

import json

from django.core.management.base import BaseCommand, CommandError

from posthog.api.property_value_cache import _make_cache_key


class Command(BaseCommand):
    help = "Show cached property values and cooldown state in Redis"

    def add_arguments(self, parser):
        parser.add_argument(
            "--team-id",
            type=int,
            help="Team ID (default: first team in the database)",
        )
        parser.add_argument(
            "--property-key",
            default="email",
            help="Property key to inspect (default: email)",
        )
        parser.add_argument(
            "--property-type",
            default="event",
            choices=["event", "person"],
            help="Property type (default: event)",
        )
        parser.add_argument(
            "--event-names",
            default="",
            help="Comma-separated event names included in the request (e.g. '$pageview'). Check network tab for event_name= params.",
        )
        parser.add_argument(
            "--all-teams",
            action="store_true",
            help="Check this property key across all teams in the database",
        )
        parser.add_argument(
            "--dump",
            action="store_true",
            help="Dump every property_values:* key currently in Redis",
        )

    def handle(self, *args, **options):
        from posthog.models.team.team import Team
        from posthog.redis import get_client

        redis_client = get_client()

        if options["dump"]:
            self._dump_all(redis_client)
            return

        property_key = options["property_key"]
        property_type = options["property_type"]
        event_names = [e.strip() for e in options["event_names"].split(",") if e.strip()] or None

        if options["all_teams"]:
            teams = list(Team.objects.order_by("id").values_list("id", "name"))
        else:
            team_id = options["team_id"]
            if team_id is None:
                team = Team.objects.order_by("id").first()
                if team is None:
                    raise CommandError("No teams found. Create a team first or pass --team-id.")
                team_id = team.pk
                self.stdout.write(f"No --team-id given, using team {team_id} ({team.name})\n")
            else:
                if not Team.objects.filter(pk=team_id).exists():
                    raise CommandError(f"Team {team_id} not found.")
            teams = [(team_id, None)]

        for team_id, team_name in teams:
            label = f"team {team_id}" + (f" ({team_name})" if team_name else "")
            cache_key = _make_cache_key(team_id, property_type, property_key, event_names=event_names)
            cooldown_key = cache_key + ":refreshing"

            self.stdout.write(f"\n{label} — {property_type}/{property_key}")
            self.stdout.write(f"  Redis key:    {cache_key}")

            raw = redis_client.get(cache_key)
            if raw is None:
                self.stdout.write(self.style.WARNING("  Cache: MISS"))
            else:
                try:
                    values = json.loads(raw)
                    names = [v.get("name", v) for v in values]
                    ttl = redis_client.ttl(cache_key)
                    self.stdout.write(
                        self.style.SUCCESS(f"  Cache: HIT — {len(values)} value(s): {', '.join(str(n) for n in names)}")
                    )
                    self.stdout.write(f"  TTL: {ttl}s")
                except (json.JSONDecodeError, AttributeError):
                    self.stdout.write(self.style.ERROR(f"  Cache: HIT but malformed — raw: {raw!r}"))

            cooldown_ttl = redis_client.ttl(cooldown_key)
            if redis_client.exists(cooldown_key):
                self.stdout.write(
                    self.style.WARNING(f"  Cooldown: SET (expires in {cooldown_ttl}s) → API returns refreshing=false")
                )
            else:
                self.stdout.write(f"  Cooldown: not set → API returns refreshing=true")

    def _dump_all(self, redis_client):
        keys = sorted([k.decode() if isinstance(k, bytes) else k for k in redis_client.keys("property_values:*")])
        self.stdout.write(f"\n=== All property_values:* keys in Redis ({len(keys)}) ===")
        for key in keys:
            if key.endswith(":refreshing"):
                ttl = redis_client.ttl(key)
                self.stdout.write(self.style.WARNING(f"  [cooldown] {key} (TTL {ttl}s)"))
                continue
            raw = redis_client.get(key)
            ttl = redis_client.ttl(key)
            if raw:
                try:
                    parsed = json.loads(raw)
                    names = [v.get("name", v) for v in parsed]
                    self.stdout.write(f"  {key} (TTL {ttl}s): {names}")
                except Exception:
                    self.stdout.write(f"  {key}: (malformed)")
            else:
                self.stdout.write(f"  {key}: (empty)")
