from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1198_filesystem_surface_indexes"),
    ]

    operations = [
        # Nullable with no DB-level default so each add is metadata-only on PG 11+ (no table
        # rewrite, no row backfill). Legacy rows stay NULL and are read as the default surface
        # ("web") in code via surface_q().
        migrations.AddField(
            model_name="filesystemshortcut",
            name="surface",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name="filesystemviewlog",
            name="surface",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name="persistedfolder",
            name="surface",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
    ]
