# Generated manually

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0952_add_billable_action_to_hogflows"),
    ]

    operations = [
        migrations.CreateModel(
            name="TeamCoreEventsConfig",
            fields=[
                (
                    "team",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        serialize=False,
                        to="posthog.team",
                    ),
                ),
                ("_core_events", models.JSONField(blank=True, db_column="core_events", default=list, null=True)),
            ],
            options={
                "verbose_name": "Team Core Events Config",
                "verbose_name_plural": "Team Core Events Configs",
            },
        ),
    ]
