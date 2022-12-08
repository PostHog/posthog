# Generated by Django 3.2.16 on 2022-12-08 08:32

from django.db import migrations

import posthog.models.utils


class Migration(migrations.Migration):
    atomic: bool = False

    dependencies = [
        ("posthog", "0283_prompt_sequence_model"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="insightcachingstate",
            constraint=posthog.models.utils.UniqueConstraintByExpression(
                concurrently=True,
                expression="(insight_id, coalesce(dashboard_tile_id, -1))",
                name="unique_insight_tile_idx",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="insightcachingstate",
            name="unique_dashboard_tile_idx",
        ),
        migrations.RemoveConstraint(
            model_name="insightcachingstate",
            name="unique_insight_for_caching_state_idx",
        ),
    ]
