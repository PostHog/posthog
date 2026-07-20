from django.core.management.base import BaseCommand

from ee.models.rbac.access_control import AccessControl


class Command(BaseCommand):
    help = (
        "Backfill 'tagger' access controls from existing 'llm_analytics' ones. Taggers used to be "
        "governed by the umbrella 'llm_analytics' RBAC resource but now have their own top-level "
        "resource ('tagger' is not in RESOURCE_INHERITANCE_MAP, so it does not fall back to "
        "'llm_analytics' at read time). Anyone who was granted a resource-wide access_level on "
        "'llm_analytics' needs an equivalent row on 'tagger' to keep the same effective permissions. "
        "Only resource-wide rows (resource_id is null) are copied: per-object grants on llm_analytics "
        "sub-resources (datasets, evaluations, score definitions, etc.) reference primary keys from "
        "unrelated models and must not be mirrored onto 'tagger'. Idempotent: safe to run more than once."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--team-id",
            type=int,
            help="Limit the backfill to a single team id. Defaults to every team.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Compute the changes without writing anything.",
        )

    def handle(self, *args, **options):
        team_id: int | None = options.get("team_id")
        dry_run: bool = options["dry_run"]

        if dry_run:
            self.stdout.write(self.style.WARNING("Running in DRY RUN mode — no changes will be made"))

        source_qs = AccessControl.objects.filter(resource="llm_analytics", resource_id__isnull=True)
        if team_id is not None:
            source_qs = source_qs.filter(team_id=team_id)

        total = 0
        created = 0
        updated = 0
        skipped = 0

        # select_related so the .first() lookups below don't re-fetch these per row.
        for source in source_qs.select_related("organization_member", "role").iterator(chunk_size=200):
            total += 1

            existing = AccessControl.objects.filter(
                team_id=source.team_id,
                resource="tagger",
                resource_id=None,
                organization_member=source.organization_member,
                role=source.role,
            ).first()

            if existing is not None:
                if existing.access_level == source.access_level:
                    skipped += 1
                    continue

                self.stdout.write(
                    f"  team={source.team_id} organization_member={source.organization_member_id} "
                    f"role={source.role_id} tagger access_level={existing.access_level!r} -> {source.access_level!r}"
                )
                updated += 1
                if not dry_run:
                    existing.access_level = source.access_level
                    existing.save(update_fields=["access_level", "updated_at"])
                continue

            self.stdout.write(
                f"  team={source.team_id} organization_member={source.organization_member_id} "
                f"role={source.role_id} new tagger access_level={source.access_level!r}"
            )
            created += 1
            if not dry_run:
                AccessControl.objects.create(
                    team_id=source.team_id,
                    resource="tagger",
                    resource_id=None,
                    organization_member=source.organization_member,
                    role=source.role,
                    access_level=source.access_level,
                    created_by=source.created_by,
                )

        verb = "Would create" if dry_run else "Created"
        update_verb = "Would update" if dry_run else "Updated"
        self.stdout.write(
            self.style.SUCCESS(
                f"Scanned {total} resource-wide 'llm_analytics' access controls. "
                f"{verb} {created} and {update_verb.lower()} {updated} 'tagger' rows. "
                f"Skipped {skipped} already in sync."
            )
        )
