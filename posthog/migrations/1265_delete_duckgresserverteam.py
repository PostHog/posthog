from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("posthog", "1264_delete_revenue_analytics_user_product_list")]

    operations = [
        # State-only: per-team managed-warehouse state now lives in the duckgres
        # control plane, so the model goes, but the posthog_duckgresserverteam table
        # is kept for now (deploy safety: old code may still read it mid-rollout).
        # A later RunSQL migration can DROP TABLE once this has been out for a full
        # deploy cycle.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(name="DuckgresServerTeam"),
            ],
            database_operations=[],
        ),
    ]
