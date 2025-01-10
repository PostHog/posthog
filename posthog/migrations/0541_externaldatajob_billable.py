# Generated by Django 4.2.15 on 2025-01-10 12:04

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0540_team_human_friendly_comparison_periods"),
    ]

    operations = [
        migrations.AddField(
            model_name="externaldatajob",
            name="billable",
            field=models.BooleanField(null=True, blank=True, default=True),
        ),
        migrations.RunSQL(
            """
            UPDATE posthog_externaldatajob
            SET billable = CASE
                WHEN pipeline_version = 'v2-non-dlt' THEN false
                ELSE true
            END""",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
