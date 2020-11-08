import django.contrib.postgres.fields.jsonb
from django.db import migrations

import posthog.models.user


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0139_dashboard_tagging"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="events_column_config",
            field=django.contrib.postgres.fields.jsonb.JSONField(
                default=posthog.models.user.events_column_config_default
            ),
        ),
    ]
