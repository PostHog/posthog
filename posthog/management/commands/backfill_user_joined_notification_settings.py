from typing import Any

from django.core.management.base import BaseCommand
from django.db import connection, transaction

ORG_MEMBER_JOIN_KEY = "organization_member_join_email_disabled"
BATCH_SIZE = 5000

COUNT_SQL = f"""
SELECT COUNT(*) FROM (
  SELECT m.user_id
  FROM posthog_organizationmembership m
  JOIN posthog_organization o ON o.id = m.organization_id
  JOIN posthog_user u ON u.id = m.user_id
  WHERE NOT COALESCE(u.partial_notification_settings, '{{}}')::jsonb ? '{ORG_MEMBER_JOIN_KEY}'
  GROUP BY m.user_id
) t
"""

UPDATE_BATCH_SQL = f"""
WITH eligible AS (
  SELECT u.id
  FROM posthog_user u
  WHERE EXISTS (
    SELECT 1 FROM posthog_organizationmembership m WHERE m.user_id = u.id
  )
  AND NOT COALESCE(u.partial_notification_settings, '{{}}')::jsonb ? '{ORG_MEMBER_JOIN_KEY}'
  ORDER BY u.id
  LIMIT {BATCH_SIZE}
),
org_map AS (
  SELECT
    m.user_id,
    jsonb_object_agg(
      m.organization_id::text,
      NOT COALESCE(o.is_member_join_email_enabled, true)
    ) AS from_orgs
  FROM posthog_organizationmembership m
  JOIN posthog_organization o ON o.id = m.organization_id
  INNER JOIN eligible e ON e.id = m.user_id
  GROUP BY m.user_id
)
UPDATE posthog_user u
SET partial_notification_settings = (
  COALESCE(u.partial_notification_settings::jsonb, '{{}}'::jsonb)
  || jsonb_build_object(
    '{ORG_MEMBER_JOIN_KEY}',
    org_map.from_orgs
  )
)
FROM org_map
WHERE u.id = org_map.user_id
"""


class Command(BaseCommand):
    help = (
        "Backfill user partial_notification_settings.organization_member_join_email_disabled from each "
        "organization's is_member_join_email_enabled for organizations the user belongs to."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show how many users would be updated without writing changes.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        dry_run: bool = options["dry_run"]

        with connection.cursor() as cursor:
            cursor.execute(COUNT_SQL)
            row = cursor.fetchone()
            assert row is not None
            (would_update,) = row

        self.stdout.write(
            f"Users with at least one organization membership and no '{ORG_MEMBER_JOIN_KEY}' "
            f"setting yet: {would_update}"
        )

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run — no changes written."))
            return

        total_updated = 0
        batch_index = 0
        while True:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(UPDATE_BATCH_SQL)
                    updated = cursor.rowcount
            if updated == 0:
                break
            total_updated += updated
            batch_index += 1
            self.stdout.write(f"Batch {batch_index}: updated {updated} user(s) (running total: {total_updated}).")

        self.stdout.write(self.style.SUCCESS(f"Done. Updated {total_updated} user(s) in {batch_index} batch(es)."))
