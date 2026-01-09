from django.core.management.base import BaseCommand

from posthog.models.feature_flag import FeatureFlag

# Raw SQL to find flags with legacy "is" operator (used as a subquery filter)
INVALID_OPERATOR_SQL = """
    SELECT 1 FROM jsonb_array_elements(posthog_featureflag.filters::jsonb->'groups') as grp,
                  jsonb_array_elements(grp->'properties') as prop
    WHERE prop->>'operator' = 'is'
"""


class Command(BaseCommand):
    help = "Fix feature flags with legacy 'is' operator (converts to 'exact')"

    def add_arguments(self, parser):
        parser.add_argument("--team-id", default=None, type=int, help="Limit to a specific team ID")
        parser.add_argument("--live-run", action="store_true", help="Apply changes (default is dry-run)")

    def handle(self, *args, **options):
        live_run = options.get("live_run", False)
        team_id = options.get("team_id")

        mode = "LIVE RUN" if live_run else "DRY RUN"
        self.stdout.write(f"Starting fix_invalid_flag_operators ({mode})")

        # Only fetch flags that have the legacy "is" operator (efficient DB-level filter)
        # nosemgrep: python.django.security.audit.query-set-extra.avoid-query-set-extra (INVALID_OPERATOR_SQL is a static constant, admin-only command)
        flags = FeatureFlag.objects.filter(deleted=False).extra(where=[f"EXISTS ({INVALID_OPERATOR_SQL})"])
        if team_id:
            flags = flags.filter(team_id=team_id)
            self.stdout.write(f"Filtering to team_id={team_id}")

        fixed_count = 0
        flags_to_update = []

        for flag in flags.iterator():
            filters = flag.filters or {}
            groups = filters.get("groups", [])
            modified = False

            for group_idx, group in enumerate(groups):
                properties = group.get("properties", [])
                for prop_idx, prop in enumerate(properties):
                    operator = prop.get("operator")

                    if operator == "is":
                        self.stdout.write(
                            f"  Flag id={flag.id} team_id={flag.team_id} key='{flag.key}': "
                            f"group[{group_idx}].properties[{prop_idx}].operator 'is' -> 'exact'"
                        )
                        prop["operator"] = "exact"
                        modified = True
                        fixed_count += 1

            if modified:
                flag.filters = filters
                flags_to_update.append(flag)

        if live_run and flags_to_update:
            FeatureFlag.objects.bulk_update(flags_to_update, ["filters"])
            self.stdout.write(self.style.SUCCESS(f"  Saved {len(flags_to_update)} flags"))

        self.stdout.write(f"Completed ({mode}): {fixed_count} properties fixed across {len(flags_to_update)} flags")

        if not live_run and fixed_count > 0:
            self.stdout.write(self.style.NOTICE("Run with --live-run to apply changes"))
