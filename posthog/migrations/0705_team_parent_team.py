# Generated by Django 4.2.18 on 2025-04-05 23:54

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    atomic = False  # Added to support concurrent index creation
    dependencies = [
        ("posthog", "0704_productintent_contexts"),
    ]

    operations = [
        # Add "parent_team" to the team. Splitting state and database operations to add the index concurrently
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="team",
                    name="parent_team",
                    field=models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="child_teams",
                        related_query_name="child_team",
                        to="posthog.team",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    """
                    ALTER TABLE "posthog_team" ADD COLUMN "parent_team_id" bigint NULL CONSTRAINT "posthog_team_parent_team_id_bkr8e799nE_fk_posthog_p" REFERENCES "posthog_team"("id") DEFERRABLE INITIALLY DEFERRED;
                    SET CONSTRAINTS "posthog_team_parent_team_id_bkr8e799nE_fk_posthog_p" IMMEDIATE;""",
                    reverse_sql="""
                        ALTER TABLE "posthog_team" DROP COLUMN IF EXISTS "parent_team_id";""",
                ),
                # We add CONCURRENTLY to the create command
                migrations.RunSQL(
                    """
                    CREATE INDEX CONCURRENTLY "posthog_team_parent_team_id_bkr8e799nE_TkKe5yC3C5" ON "posthog_team" ("parent_team_id");""",
                    reverse_sql="""
                        DROP INDEX IF EXISTS "posthog_team_parent_team_id_bkr8e799nE_TkKe5yC3C5";""",
                ),
            ],
        ),
    ]
