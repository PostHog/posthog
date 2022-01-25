# Generated by Django 3.2.5 on 2022-01-25 17:33

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0199_update_experiment_model"),
    ]

    operations = [
        migrations.AddField(
            model_name="insight",
            name="last_modified_at",
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
        migrations.AddField(
            model_name="insight",
            name="last_modified_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="modified_insights",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
