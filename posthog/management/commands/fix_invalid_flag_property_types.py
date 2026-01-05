from django.core.management.base import BaseCommand

from posthog.models.feature_flag import FeatureFlag

# Valid property types for feature flags (from validate_filters in api/feature_flag.py)
VALID_PROPERTY_TYPES = {"person", "cohort", "group", "flag"}

# Map of invalid types to their correct replacement
TYPE_FIXES = {
    "event": "person",  # Django treats "event" the same as "person" for backwards compatibility
}

# Raw SQL to find flags with invalid property types (used as a subquery filter)
INVALID_FLAGS_SQL = """
    SELECT 1 FROM jsonb_array_elements(posthog_featureflag.filters::jsonb->'groups') as grp,
                  jsonb_array_elements(grp->'properties') as prop
    WHERE prop->>'type' NOT IN ('person', 'cohort', 'group', 'flag')
      AND prop->>'type' IS NOT NULL
"""


class Command(BaseCommand):
    help = "Fix feature flags with invalid property types (e.g., 'event' -> 'person')"

    def add_arguments(self, parser):
        parser.add_argument("--team-id", default=None, type=int, help="Limit to a specific team ID")
        parser.add_argument("--live-run", action="store_true", help="Apply changes (default is dry-run)")

    def handle(self, *args, **options):
        live_run = options.get("live_run", False)
        team_id = options.get("team_id")

        mode = "LIVE RUN" if live_run else "DRY RUN"
        self.stdout.write(f"Starting fix_invalid_flag_property_types ({mode})")

        # Only fetch flags that have invalid property types (efficient DB-level filter)
        flags = FeatureFlag.objects.filter(deleted=False, active=True).extra(where=[f"EXISTS ({INVALID_FLAGS_SQL})"])
        if team_id:
            flags = flags.filter(team_id=team_id)
            self.stdout.write(f"Filtering to team_id={team_id}")

        fixed_count = 0
        unfixable_count = 0
        flags_to_update = []

        for flag in flags.iterator():
            filters = flag.filters or {}
            groups = filters.get("groups", [])
            modified = False

            for group_idx, group in enumerate(groups):
                properties = group.get("properties", [])
                for prop_idx, prop in enumerate(properties):
                    prop_type = prop.get("type")

                    if prop_type and prop_type not in VALID_PROPERTY_TYPES:
                        if prop_type in TYPE_FIXES:
                            new_type = TYPE_FIXES[prop_type]
                            self.stdout.write(
                                f"  Flag id={flag.id} team_id={flag.team_id} key='{flag.key}': "
                                f"group[{group_idx}].properties[{prop_idx}].type '{prop_type}' -> '{new_type}'"
                            )
                            prop["type"] = new_type
                            modified = True
                            fixed_count += 1
                        else:
                            self.stdout.write(
                                self.style.WARNING(
                                    f"  Flag id={flag.id} team_id={flag.team_id} key='{flag.key}': "
                                    f"group[{group_idx}].properties[{prop_idx}].type '{prop_type}' has no known fix"
                                )
                            )
                            unfixable_count += 1

            if modified:
                flag.filters = filters
                flags_to_update.append(flag)

        if live_run and flags_to_update:
            FeatureFlag.objects.bulk_update(flags_to_update, ["filters"])
            self.stdout.write(self.style.SUCCESS(f"  Saved {len(flags_to_update)} flags"))

        self.stdout.write(f"Completed ({mode}): {fixed_count} properties fixed, {unfixable_count} unfixable")

        if not live_run and fixed_count > 0:
            self.stdout.write(self.style.NOTICE("Run with --live-run to apply changes"))
