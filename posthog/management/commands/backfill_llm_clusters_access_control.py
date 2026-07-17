import logging

from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Mirror every existing 'llm_analytics' AccessControl row onto a matching 'llm_clusters' row. "
        "Clustering used to inherit its access level from llm_analytics; now that it's an independent "
        "resource, this backfill keeps existing grants working instead of silently defaulting to none. "
        "Idempotent - safe to re-run."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be created without writing.",
        )

    def handle(self, *args, **options):
        from ee.models.rbac.access_control import AccessControl

        dry_run: bool = options["dry_run"]

        total = 0
        created = 0
        already_existed = 0

        for row in AccessControl.objects.filter(resource="llm_analytics").iterator(chunk_size=200):
            total += 1
            target_filter = {
                "resource": "llm_clusters",
                "resource_id": row.resource_id,
                "team_id": row.team_id,
                "organization_member_id": row.organization_member_id,
                "role_id": row.role_id,
            }
            if AccessControl.objects.filter(**target_filter).exists():
                already_existed += 1
                continue

            created += 1
            self.stdout.write(
                f"team={row.team_id} organization_member={row.organization_member_id} "
                f"role={row.role_id} access_level={row.access_level}"
            )
            if not dry_run:
                AccessControl.objects.get_or_create(
                    **target_filter,
                    defaults={"access_level": row.access_level, "created_by": row.created_by},
                )

        verb = "Would create" if dry_run else "Created"
        self.stdout.write(
            f"{verb} {created}/{total} llm_clusters AccessControl rows ({already_existed} already existed)."
        )
