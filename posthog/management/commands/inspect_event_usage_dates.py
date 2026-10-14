import json
from argparse import ArgumentParser
from datetime import UTC, datetime, timedelta
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import ClickHouseUser, Workload


def inspect_event_usage_dates(*, team_id: int, capture_day: datetime) -> list[dict[str, str | int]]:
    rows = sync_execute(
        """
        SELECT usage_key, unit,
            multiIf(
                NOT match(record_id, '^[0-9]{4}-[0-9]{2}-[0-9]{2}:[0-9a-f]{32}$') OR isNull(source_date), 'unknown',
                source_date < toDate(%(begin)s), 'earlier',
                source_date > toDate(%(begin)s), 'later',
                'same_day'
            ) AS source_period,
            sum(quantity)
        FROM (
            SELECT usage_key, unit, record_id, quantity, toDateOrNull(substring(record_id, 1, 10)) AS source_date
            FROM billing_usage_records FINAL
            WHERE team_id = %(team_id)s
              AND usage_key IN ('events', 'enhanced_person_events')
              AND timestamp >= %(begin)s AND timestamp < %(end)s
        )
        GROUP BY usage_key, unit, source_period
        ORDER BY usage_key, unit, source_period
        """,
        {"team_id": team_id, "begin": capture_day, "end": capture_day + timedelta(days=1)},
        workload=Workload.OFFLINE,
        ch_user=ClickHouseUser.BILLING,
        settings={
            "max_execution_time": 30,
            "max_memory_usage": 1024**3,
            "max_bytes_to_read": 10 * 1024**3,
            "max_threads": 2,
        },
    )
    return [
        {"usage_key": key, "unit": unit, "source_period": period, "quantity": int(count)}
        for key, unit, period, count in rows
    ]


class Command(BaseCommand):
    help = "Break down received event usage by source date without changing its billing period (read only)."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--capture-date", required=True, help="UTC date, YYYY-MM-DD")

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            capture_day = datetime.strptime(options["capture_date"], "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError as error:
            raise CommandError("--capture-date must be YYYY-MM-DD") from error
        if options["team_id"] <= 0:
            raise CommandError("--team-id must be positive")
        self.stdout.write(
            json.dumps(
                {
                    "team_id": options["team_id"],
                    "capture_date": options["capture_date"],
                    "billing_clock": "capture_time",
                    "source_date_location": "record_id prefix",
                    "note": "Earlier and later source dates explain period differences; this is not a source-day reconciliation with legacy reports.",
                    "counts": inspect_event_usage_dates(team_id=options["team_id"], capture_day=capture_day),
                }
            )
        )
