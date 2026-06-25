from django.db import migrations


class Migration(migrations.Migration):
    """Physically drop the objects 1241 removed from Django state only.

    1241 stopped Django from managing DuckLakeCatalog, DuckLakeBackfill, and
    DuckgresServer.team (state-only), but left the tables/column in place so old workers could
    keep reading them during the consolidation rollout. Run this ONLY after that PR has fully
    deployed and every worker is on the new code (which no longer references them). The objects
    are out of Django's state, so the drops are raw SQL. Irreversible.
    """

    dependencies = [
        ("posthog", "1241_consolidate_duckgres_models_drop"),
    ]

    operations = [
        migrations.RunSQL(
            sql='ALTER TABLE "posthog_duckgresserver" DROP COLUMN IF EXISTS "team_id";',
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql='DROP TABLE IF EXISTS "posthog_ducklakecatalog";',
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql='DROP TABLE IF EXISTS "posthog_ducklakebackfill";',
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
