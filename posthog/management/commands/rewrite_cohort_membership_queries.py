from collections.abc import Callable

from django.core.management.base import BaseCommand

from posthog.models.cohortmembership.query_rewrite import LEGACY_TABLE, SavedQueryRewrite

from products.data_modeling.backend.facade import api as data_modeling_api
from products.endpoints.backend.facade import api as endpoints_api
from products.notebooks.backend.facade import api as notebooks_api
from products.product_analytics.backend.facade import api as product_analytics_api

REWRITERS: tuple[Callable[[int, bool], list[SavedQueryRewrite]], ...] = (
    product_analytics_api.rewrite_cohort_membership_queries,
    data_modeling_api.rewrite_cohort_membership_queries,
    notebooks_api.rewrite_cohort_membership_queries,
    endpoints_api.rewrite_cohort_membership_queries,
)


class Command(BaseCommand):
    help = "Point a team's saved HogQL that reads the `cohort_membership` table at `cohort_people`."

    def add_arguments(self, parser):
        parser.add_argument(
            "--team-id", type=int, action="append", required=True, help="Team to rewrite. Repeat for several teams."
        )
        parser.add_argument(
            "--apply", action="store_true", help="Write the rewrites. Without it, the command only reports them."
        )
        parser.add_argument("--show-sql", action="store_true", help="Also print each query before and after.")

    def handle(self, *args, **options):
        apply: bool = options["apply"]
        show_sql: bool = options["show_sql"]
        changed, manual, stale = 0, 0, 0
        for team_id in options["team_id"]:
            for rewrite_team in REWRITERS:
                for row in rewrite_team(team_id, apply):
                    changed += row.written if apply else row.changed
                    manual += row.needs_manual_check
                    stale += apply and row.changed and not row.written
                    self._write_row(row, apply, show_sql)
        verb = "Rewrote" if apply else "Would rewrite"
        self.stdout.write(
            f"{verb} {changed} rows. {manual} rows need a manual check. {stale} rows changed while running."
        )

    def _write_row(self, row: SavedQueryRewrite, apply: bool, show_sql: bool) -> None:
        self.stdout.write(f"{row.source} {row.pk} (team {row.team_id}):")
        if apply and row.changed and not row.written:
            self.stdout.write("  changed while running, not written; run again")
        # A query left for a manual fix also keeps the name, so the line below would point at the wrong place.
        if row.still_mentions_table and not any(rewrite.needs_manual_fix for rewrite in row.rewrites):
            self.stdout.write(f"  still names {LEGACY_TABLE} outside a query this command rewrites")
        for rewrite in row.rewrites:
            if rewrite.needs_manual_fix:
                self.stdout.write("  a query needs a manual fix")
            if show_sql:
                self.stdout.write(f"  before: {rewrite.before}")
                self.stdout.write(f"  after:  {rewrite.after}")
