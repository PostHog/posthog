from typing import Any

from django.core.management.base import BaseCommand
from django.db import connection, transaction

ORG_MEMBER_JOIN_KEY = "organization_member_join_email_disabled"

COUNT_SQL = """
SELECT COUNT(*) FROM (
  SELECT m.user_id
  FROM posthog_organizationmembership m
  JOIN posthog_organization o ON o.id = m.organization_id
  GROUP BY m.user_id
) t
"""

UPDATE_SQL = f"""
UPDATE posthog_user u
SET partial_notification_settings = (
  COALESCE(u.partial_notification_settings::jsonb, '{{}}'::jsonb)
  || jsonb_build_object(
    '{ORG_MEMBER_JOIN_KEY}',
    COALESCE(u.partial_notification_settings::jsonb #> '{{{ORG_MEMBER_JOIN_KEY}}}', '{{}}'::jsonb)
    || org_map.from_orgs
  )
)
FROM (
  SELECT
    m.user_id,
    jsonb_object_agg(
      m.organization_id::text,
      NOT COALESCE(o.is_member_join_email_enabled, true)
    ) AS from_orgs
  FROM posthog_organizationmembership m
  JOIN posthog_organization o ON o.id = m.organization_id
  GROUP BY m.user_id
) org_map
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

        self.stdout.write(f"Users with at least one organization membership to process: {would_update}")

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run — no changes written."))
            return

        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(UPDATE_SQL)
                updated = cursor.rowcount

        self.stdout.write(self.style.SUCCESS(f"Updated {updated} user(s)."))
