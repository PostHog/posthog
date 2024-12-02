# Generated by Django 4.2.15 on 2024-11-29 16:21

from django.db import migrations, models
import django.db.models.deletion
import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0523_errortrackingsymbolset_content_hash"),
    ]

    operations = [
        migrations.CreateModel(
            name="RemoteConfig",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.UUIDT, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("config", models.JSONField()),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("synced_at", models.DateTimeField(null=True)),
                ("team", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to="posthog.team")),
            ],
            options={
                "abstract": False,
            },
        ),
    ]
