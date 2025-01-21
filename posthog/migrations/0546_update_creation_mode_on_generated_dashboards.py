# Generated by Django 4.2.15 on 2025-01-17 22:28

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0545_insight_filters_to_query"),
    ]

    operations = [
        migrations.RunSQL(
            """
            UPDATE posthog_dashboard
            SET creation_mode = 'template'
            WHERE name LIKE 'Generated Dashboard: % Usage'
            AND description LIKE 'This dashboard was generated by the feature flag with key (%)'
            AND creation_mode = 'default'
            """,
            reverse_sql="""
            UPDATE posthog_dashboard
            SET creation_mode = 'default'
            WHERE name LIKE 'Generated Dashboard: % Usage'
            AND description LIKE 'This dashboard was generated by the feature flag with key (%)'
            AND creation_mode = 'template'
            """,
        ),
    ]
