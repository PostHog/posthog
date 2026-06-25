from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1240_consolidate_duckgres_models_data"),
    ]

    operations = [
        # Deprecated: membership now lives in DuckgresServerTeam, so the server is purely
        # org-scoped and no longer carries a team.
        migrations.RemoveField(
            model_name="duckgresserver",
            name="team",
        ),
        # Folded into DuckgresServer (DuckLakeCatalog) and DuckgresServerTeam (DuckLakeBackfill).
        migrations.DeleteModel(
            name="DuckLakeCatalog",
        ),
        migrations.DeleteModel(
            name="DuckLakeBackfill",
        ),
    ]
