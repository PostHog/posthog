# Generated by Django 3.2.19 on 2024-01-16 19:56

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0386_add_session_replay_config_to_team"),
    ]

    operations = [
        migrations.AlterField(
            model_name="externaldatasource",
            name="source_type",
            field=models.CharField(
                choices=[("Stripe", "Stripe"), ("Hubspot", "Hubspot"), ("Postgres", "Postgres")], max_length=128
            ),
        ),
    ]
