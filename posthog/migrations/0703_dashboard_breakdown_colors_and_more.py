# Generated by Django 4.2.18 on 2025-03-31 20:17

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    atomic = False  # Added to support concurrent index creation
    dependencies = [("posthog", "0703_dashboard_breakdown_colors_and_more")]

    operations = [
        migrations.AddField(
            model_name="dashboard",
            name="breakdown_colors",
            field=models.JSONField(blank=True, default=list, null=True),
        ),
        # Safely add foreign key by using CONCURRENTLY. See `0415_pluginconfig_match_action` for reference.
        # https://docs.djangoproject.com/en/4.2/ref/contrib/postgres/operations/#concurrent-index-operations.
        #
        # migrations.AddField(
        #     model_name="dashboard",
        #     name="data_color_theme",
        #     field=models.ForeignKey(
        #         blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="posthog.datacolortheme"
        #     ),
        # ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="dashboard",
                    name="data_color_theme",
                    field=models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="posthog.datacolortheme",
                    ),
                )
            ],
            database_operations=[
                # We add -- existing-table-constraint-ignore to ignore the constraint validation in CI.
                migrations.RunSQL(
                    """
                    ALTER TABLE "posthog_dashboard" ADD COLUMN "data_color_theme_id" integer NULL CONSTRAINT "posthog_dashboard_data_color_theme_id_0084ccbf_fk_posthog_d" REFERENCES "posthog_datacolortheme"("id") DEFERRABLE INITIALLY DEFERRED; -- existing-table-constraint-ignore
                    SET CONSTRAINTS "posthog_dashboard_data_color_theme_id_0084ccbf_fk_posthog_d" IMMEDIATE; -- existing-table-constraint-ignore
                    """,
                    reverse_sql="""
                        ALTER TABLE "posthog_dashboard" DROP COLUMN IF EXISTS "data_color_theme_id";
                    """,
                ),
                # We add CONCURRENTLY to the create command
                migrations.RunSQL(
                    """
                    CREATE INDEX CONCURRENTLY "posthog_dashboard_data_color_theme_id_0084ccbf" ON "posthog_dashboard" ("data_color_theme_id");
                    """,
                    reverse_sql="""
                        DROP INDEX IF EXISTS "posthog_dashboard_data_color_theme_id_0084ccbf";
                    """,
                ),
            ],
        ),
    ]
