from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1084_ducklake_add_organization_fk"),
    ]

    operations = [
        # Backfill organization_id from team.organization_id for existing rows.
        # These are tiny tables (single-digit rows) so a simple UPDATE is safe.
        # The NOT EXISTS guard prevents UniqueViolation if two teams in the same
        # org both have a row — only the first one wins. In practice this shouldn't
        # happen (one catalog/server per org is the invariant), but the guard makes
        # the migration safe regardless.
        migrations.RunSQL(
            sql="""
                -- migration-analyzer: safe reason=posthog_ducklakecatalog has <10 rows (near empty, single-tenant configs only)
                UPDATE posthog_ducklakecatalog dlc
                SET organization_id = t.organization_id
                FROM posthog_team t
                WHERE dlc.team_id = t.id
                  AND dlc.organization_id IS NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM posthog_ducklakecatalog other
                      WHERE other.organization_id = t.organization_id
                  )
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql="""
                -- migration-analyzer: safe reason=posthog_duckgresserver has <10 rows (near empty, single-tenant configs only)
                UPDATE posthog_duckgresserver ds
                SET organization_id = t.organization_id
                FROM posthog_team t
                WHERE ds.team_id = t.id
                  AND ds.organization_id IS NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM posthog_duckgresserver other
                      WHERE other.organization_id = t.organization_id
                  )
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
