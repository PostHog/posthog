import copy

from django.core.management.base import BaseCommand

from products.feature_flags.backend.facade.config import detect_config_format
from products.feature_flags.backend.flag_status import jsonb_array_or_empty
from products.feature_flags.backend.models.feature_flag import FeatureFlag

# Valid property types for feature flags (from validate_filters in api/feature_flag.py)
VALID_PROPERTY_TYPES = {"person", "cohort", "group", "flag"}

# Map of invalid types to their correct replacement
TYPE_FIXES = {
    "event": "person",  # Django treats "event" the same as "person" for backwards compatibility
}

# Raw SQL to find flags with invalid property types (used as a subquery filter)
_GROUPS_ARRAY = jsonb_array_or_empty("posthog_featureflag.filters->'groups'")
_PROPERTIES_ARRAY = jsonb_array_or_empty("grp->'properties'")
INVALID_FLAGS_SQL = f"""
    SELECT 1 FROM jsonb_array_elements({_GROUPS_ARRAY}) as grp,
                  jsonb_array_elements({_PROPERTIES_ARRAY}) as prop
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
        # nosemgrep: python.django.security.audit.query-set-extra.avoid-query-set-extra (INVALID_FLAGS_SQL is a static constant, admin-only command)
        flags = FeatureFlag.objects.filter(active=True).extra(where=[f"EXISTS ({INVALID_FLAGS_SQL})"])
        if team_id:
            flags = flags.filter(team_id=team_id)
            self.stdout.write(f"Filtering to team_id={team_id}")

        fixed_count = 0
        unfixable_count = 0
        skipped_count = 0
        saved_count = 0

        for flag in flags.iterator():
            label = f"  Flag id={flag.id} team_id={flag.team_id} key='{flag.key}'"
            if detect_config_format(flag.filters).kind != "v1":
                self.stdout.write(self.style.WARNING(f"{label}: config format is not 1, skipped"))
                skipped_count += 1
                continue
            filters = copy.deepcopy(flag.filters or {})
            groups = filters.get("groups") or []
            flag_fixed = 0

            for group_idx, group in enumerate(groups):
                properties = (group.get("properties") or []) if isinstance(group, dict) else []
                for prop_idx, prop in enumerate(properties):
                    prop_type = prop.get("type") if isinstance(prop, dict) else None

                    if prop_type and prop_type not in VALID_PROPERTY_TYPES:
                        if prop_type in TYPE_FIXES:
                            new_type = TYPE_FIXES[prop_type]
                            self.stdout.write(
                                f"{label}: group[{group_idx}].properties[{prop_idx}].type '{prop_type}' -> '{new_type}'"
                            )
                            prop["type"] = new_type
                            flag_fixed += 1
                        else:
                            self.stdout.write(
                                self.style.WARNING(
                                    f"{label}: group[{group_idx}].properties[{prop_idx}].type '{prop_type}' has no known fix"
                                )
                            )
                            unfixable_count += 1

            if live_run and flag_fixed:
                # Compare-and-swap on the scanned document: a row edited since the scan keeps its new value.
                if FeatureFlag.objects.filter(pk=flag.pk, filters=flag.filters).update(filters=filters):
                    saved_count += 1
                else:
                    self.stdout.write(self.style.WARNING(f"{label}: changed during the run, not saved"))
                    skipped_count += 1
                    flag_fixed = 0
            fixed_count += flag_fixed

        if live_run:
            self.stdout.write(self.style.SUCCESS(f"  Saved {saved_count} flags"))

        self.stdout.write(
            f"Completed ({mode}): {fixed_count} properties fixed, {unfixable_count} unfixable, {skipped_count} flags skipped"
        )

        if not live_run and fixed_count > 0:
            self.stdout.write(self.style.NOTICE("Run with --live-run to apply changes"))
