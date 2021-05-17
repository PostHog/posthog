# Generated by Django 3.1.8 on 2021-05-15 00:51

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('posthog', '0152_user_events_column_config'),
    ]

    operations = [
        migrations.CreateModel(
            name='Version',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('previous_state', models.JSONField(default=dict)),
                ('update', models.JSONField(default=dict)),
                ('comment', models.CharField(blank=True, max_length=400, null=True)),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
                (
                    'instance_key', models.ForeignKey(
                        blank=True, null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='versions',
                        to='posthog.dashboarditem',
                    ),
                ),
            ],
        ),
    ]
