"""Add the insight chart to Slack insight-alert destinations that predate it.

Every destination stores its own copy of the Slack blocks, so the ones created before the chart
shipped keep posting a divider where the chart now goes. This finds them and rewrites that block.
Destinations whose blocks have been edited by hand are reported and left alone.

Reports by default. Region-agnostic - run it once per region, narrowing by team first.

    python manage.py backfill_insight_alert_slack_chart_block                       # dry run
    python manage.py backfill_insight_alert_slack_chart_block --team-ids 2 --apply
    python manage.py backfill_insight_alert_slack_chart_block --apply
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from products.alerts.backend.destination_backfill import backfill_insight_alert_chart_blocks


class Command(BaseCommand):
    help = "Backfill the insight chart block into Slack insight-alert destinations created before it shipped"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-ids", type=str, default=None, help="Comma-separated team ids to limit to")
        parser.add_argument("--limit", type=int, default=None, help="Look at no more than this many destinations")
        parser.add_argument("--batch-size", type=int, default=100, help="Rows per UPDATE (default: 100)")
        parser.add_argument("--apply", action="store_true", default=False, help="Write them (default: report only)")

    def handle(self, *args: Any, **options: Any) -> None:
        apply: bool = options["apply"]
        result = backfill_insight_alert_chart_blocks(
            team_ids=_parse_team_ids(options["team_ids"]),
            limit=options["limit"],
            batch_size=options["batch_size"],
            apply=apply,
        )

        counts = [
            ("repaired" if apply else "would repair", result.repaired),
            ("already current", result.already_current),
            ("left as-is", result.left_alone),
        ]
        if result.uncompilable:
            counts.append(("would not compile, see the logs", result.uncompilable))

        width = max(len(label) for label, _ in counts)
        self.stdout.write(f"Checked {result.scanned} Slack insight-alert destination(s).")
        for label, count in counts:
            self.stdout.write(f"  {label.ljust(width)}  {count}")

        if not apply:
            self.stdout.write("Dry run. Re-run with --apply to write them.")


def _parse_team_ids(raw: str | None) -> list[int] | None:
    if raw is None:
        return None
    try:
        team_ids = [int(team_id) for team_id in raw.split(",") if team_id.strip()]
    except ValueError:
        raise CommandError("--team-ids takes comma-separated integers, for example --team-ids 2,7")
    if not team_ids:
        raise CommandError("--team-ids needs at least one team id")
    return team_ids
