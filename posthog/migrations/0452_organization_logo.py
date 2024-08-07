# Generated by Django 4.2.14 on 2024-07-22 08:06

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    atomic = False  # Added to support concurrent index creation
    dependencies = [
        ("posthog", "0451_datawarehousetable_updated_at_and_more"),
    ]

    operations = [
        # Using the approach with CREATE INDEX CONCURRENTLY from 0415_pluginconfig_match_action
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="organization",
                    name="logo_media",
                    field=models.ForeignKey(
                        blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="posthog.uploadedmedia"
                    ),
                ),
            ],
            database_operations=[
                # We add -- existing-table-constraint-ignore to ignore the constraint validation in CI.
                migrations.RunSQL(
                    """
                    ALTER TABLE "posthog_organization" ADD COLUMN "logo_media_id" uuid NULL CONSTRAINT "posthog_organization_logo_media_id_1c12c9dc_fk_posthog_u" REFERENCES "posthog_uploadedmedia"("id") DEFERRABLE INITIALLY DEFERRED; -- existing-table-constraint-ignore
                    SET CONSTRAINTS "posthog_organization_logo_media_id_1c12c9dc_fk_posthog_u" IMMEDIATE;
                    """,
                    reverse_sql="""
                        ALTER TABLE "posthog_organization" DROP COLUMN IF EXISTS "logo_media_id";
                    """,
                ),
                # We add CONCURRENTLY to the create command
                migrations.RunSQL(
                    """
                    CREATE INDEX CONCURRENTLY "posthog_organization_logo_media_id_1c12c9dc" ON "posthog_organization" ("logo_media_id");
                    """,
                    reverse_sql="""
                        DROP INDEX IF EXISTS "posthog_organization_logo_media_id_1c12c9dc";
                    """,
                ),
            ],
        ),
    ]
