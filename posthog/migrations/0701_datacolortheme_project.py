# Generated by Django 4.2.18 on 2025-04-01 18:53

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    atomic = False  # Added to support concurrent index creation
    dependencies = [
        ("posthog", "0700_datamodelingjob"),
    ]

    operations = [
        # Add "project_id" to the action. Splitting state and database operations to add the index concurrently
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="datacolortheme",
                    name="project",
                    field=models.ForeignKey(
                        null=True, blank=True, on_delete=django.db.models.deletion.CASCADE, to="posthog.project"
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    """
                    ALTER TABLE "posthog_datacolortheme" ADD COLUMN "project_id" bigint NULL CONSTRAINT "posthog_datacolortheme_project_id_CZYFwmeeLU_fk_posthog_p" REFERENCES "posthog_project"("id") DEFERRABLE INITIALLY DEFERRED;
                    SET CONSTRAINTS "posthog_datacolortheme_project_id_CZYFwmeeLU_fk_posthog_p" IMMEDIATE;""",
                    reverse_sql="""
                        ALTER TABLE "posthog_datacolortheme" DROP COLUMN IF EXISTS "project_id";""",
                ),
                # We add CONCURRENTLY to the create command
                migrations.RunSQL(
                    """
                    CREATE INDEX CONCURRENTLY "posthog_datacolortheme_project_id_CZYFwmeeLU_Rvzb4NfvcS" ON "posthog_datacolortheme" ("project_id");""",
                    reverse_sql="""
                        DROP INDEX IF EXISTS "posthog_datacolortheme_project_id_CZYFwmeeLU_Rvzb4NfvcS";""",
                ),
            ],
        ),
    ]
