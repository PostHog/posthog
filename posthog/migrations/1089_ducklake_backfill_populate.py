from django.db import migrations


def populate_from_catalogs(apps, schema_editor):
    """Create DuckLakeBackfill rows for existing DuckLakeCatalog entries."""
    DuckLakeCatalog = apps.get_model("posthog", "DuckLakeCatalog")
    DuckLakeBackfill = apps.get_model("posthog", "DuckLakeBackfill")

    backfills = [DuckLakeBackfill(team_id=catalog.team_id, enabled=True) for catalog in DuckLakeCatalog.objects.all()]
    if backfills:
        DuckLakeBackfill.objects.bulk_create(backfills, ignore_conflicts=True)


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1088_ducklake_backfill_model"),
    ]

    operations = [
        migrations.RunPython(populate_from_catalogs, migrations.RunPython.noop),
    ]
