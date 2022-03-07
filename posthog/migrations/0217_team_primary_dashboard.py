# Generated by Django 3.2.12 on 2022-03-04 22:15

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0216_insight_placeholder_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="team",
            name="primary_dashboard",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="primary_dashboard_teams",
                to="posthog.dashboard",
            ),
        ),
    ]
