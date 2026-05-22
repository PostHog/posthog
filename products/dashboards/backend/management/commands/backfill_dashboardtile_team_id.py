import time
from typing import Any

from django.core.management.base import BaseCommand
from django.db import connection, transaction

BATCH_SIZE = 5000
SLEEP_INTERVAL_SECONDS = 0.1

UPDATE_BATCH_SQL = """
UPDATE posthog_dashboardtile AS t
SET team_id = d.team_id
FROM posthog_dashboard AS d
WHERE t.dashboard_id = d.id
  AND t.team_id IS NULL
  AND t.id IN (
      SELECT id
      FROM posthog_dashboardtile
      WHERE team_id IS NULL
      ORDER BY id
      LIMIT %s
  )
"""


class Command(BaseCommand):
    help = "Backfill DashboardTile.team_id from the parent dashboard's team_id."

    def handle(self, *args: Any, **options: Any) -> None:
        total_updated = 0
        batch_index = 0

        while True:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(UPDATE_BATCH_SQL, [BATCH_SIZE])
                    updated = cursor.rowcount

            if updated == 0:
                break

            total_updated += updated
            batch_index += 1
            self.stdout.write(f"Batch {batch_index}: updated {updated} tile(s) (running total: {total_updated}).")
            time.sleep(SLEEP_INTERVAL_SECONDS)

        self.stdout.write(self.style.SUCCESS(f"Done. Updated {total_updated} tile(s) in {batch_index} batch(es)."))
