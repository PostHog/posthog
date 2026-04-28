from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1129_userintegration"),
    ]

    operations = [
        migrations.AddField(
            model_name="ducklakecatalog",
            name="ducklake_version",
            field=models.IntegerField(
                blank=True,
                choices=[(40, "0.4"), (100, "1.0")],
                default=None,
                help_text=(
                    "DuckLake catalog version deployed on this duckling. "
                    "Determines which DuckDB version must be used for backfill jobs. "
                    "0.4 requires duckdb 1.5.1; 1.0 requires duckdb 1.5.2."
                ),
                null=True,
            ),
        ),
    ]
