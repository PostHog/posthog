"""
Management command for clearing the property value Redis cache.

Cache keys are hashed (sha256), so they cannot be filtered by team without
scanning all keys. This command always operates across all teams.

Workflow:
  Dry-run to see what would be deleted:
    python manage.py bust_property_value_cache --dry-run

  Delete everything (all teams, values and cooldowns):
    python manage.py bust_property_value_cache

  Delete only the value cache, leave cooldown keys intact:
    python manage.py bust_property_value_cache --keep-cooldowns
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Delete all property value Redis cache entries (all teams)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deleted without actually deleting anything",
        )
        parser.add_argument(
            "--keep-cooldowns",
            action="store_true",
            help="Delete value cache entries but leave cooldown keys intact",
        )

    def handle(self, *args, **options):
        from posthog.redis import get_client

        dry_run = options["dry_run"]
        keep_cooldowns = options["keep_cooldowns"]

        redis_client = get_client()
        all_keys = sorted([k.decode() if isinstance(k, bytes) else k for k in redis_client.keys("property_values:*")])

        if not all_keys:
            self.stdout.write("No property_values:* keys found in Redis.")
            return

        cooldown_keys = [k for k in all_keys if k.endswith(":refreshing")]
        value_keys = [k for k in all_keys if not k.endswith(":refreshing")]

        keys_to_delete = value_keys + ([] if keep_cooldowns else cooldown_keys)

        self.stdout.write(f"Found {len(value_keys)} value key(s) and {len(cooldown_keys)} cooldown key(s).")

        if dry_run:
            self.stdout.write(self.style.WARNING(f"Dry run — would delete {len(keys_to_delete)} key(s):"))
            for key in keys_to_delete:
                self.stdout.write(f"  {key}")
            return

        if keys_to_delete:
            redis_client.delete(*keys_to_delete)

        self.stdout.write(
            self.style.SUCCESS(
                f"Deleted {len(value_keys)} value cache key(s)"
                + (f" and {len(cooldown_keys)} cooldown key(s)" if not keep_cooldowns else " (cooldowns kept)")
                + "."
            )
        )
