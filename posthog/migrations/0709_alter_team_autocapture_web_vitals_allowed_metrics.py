# Generated by Django 4.2.18 on 2025-04-09 19:47

import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0708_team_flags_require_confirmation"),
    ]

    operations = [
        # Step 1: Add a temporary column with the correct type
        migrations.AddField(
            model_name="team",
            name="autocapture_web_vitals_allowed_metrics_new",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.TextField(blank=True, null=True), blank=True, default=list, null=True, size=None
            ),
        ),
        # Step 2: Copy data from old column to new column with conversion (using a stored procedure)
        migrations.RunSQL(
            sql="""
            DO $$
            DECLARE
                team_rec RECORD;
                json_val JSONB;
                text_arr TEXT[];
            BEGIN
                FOR team_rec IN SELECT id, autocapture_web_vitals_allowed_metrics FROM posthog_team LOOP
                    json_val := team_rec.autocapture_web_vitals_allowed_metrics;
                    -- Handle NULL case
                    IF json_val IS NULL THEN
                        text_arr := NULL;
                    -- Handle empty array case
                    ELSIF json_val::text = '[]' THEN
                        text_arr := ARRAY[]::TEXT[];
                    ELSE
                        -- Convert each JSON element to text and build array
                        SELECT array_agg(value) INTO text_arr
                        FROM jsonb_array_elements_text(json_val);
                    END IF;
                    -- Update with the new array value
                    UPDATE posthog_team
                    SET autocapture_web_vitals_allowed_metrics_new = text_arr
                    WHERE id = team_rec.id;
                END LOOP;
            END $$;
            """,
            reverse_sql="",  # No need for reverse SQL as we drop the temp column in forward migration
        ),
        # Step 3: Drop the old column
        migrations.RemoveField(
            model_name="team",
            name="autocapture_web_vitals_allowed_metrics",
        ),
        # Step 4: Rename the new column to the original name
        migrations.RenameField(
            model_name="team",
            old_name="autocapture_web_vitals_allowed_metrics_new",
            new_name="autocapture_web_vitals_allowed_metrics",
        ),
    ]
