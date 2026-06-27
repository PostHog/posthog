from django.db import migrations


class Migration(migrations.Migration):
    """Remove the folded-in models from Django state only.

    The data has already moved onto DuckgresServer / DuckgresServerTeam (1241). Here we drop
    DuckLakeCatalog, DuckLakeBackfill, and the deprecated DuckgresServer.team from Django's
    *state* but emit no SQL, so the tables/column physically remain. This keeps old code
    (still reading those tables during a rolling deploy) working; a follow-up migration drops
    the physical objects once every worker is on the new code. See
    docs/.../safe-django-migrations.md#dropping-tables.
    """

    dependencies = [
        ("posthog", "1241_consolidate_duckgres_models_data"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name="duckgresserver",
                    name="team",
                ),
                migrations.DeleteModel(
                    name="DuckLakeCatalog",
                ),
                migrations.DeleteModel(
                    name="DuckLakeBackfill",
                ),
            ],
            database_operations=[],
        ),
    ]
