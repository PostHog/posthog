import django.db.models.deletion
import django.contrib.postgres.fields.jsonb
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0095_session_recording_event_table"),
    ]

    operations = [
        migrations.CreateModel(
            name="Plugin",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(blank=True, max_length=200, null=True)),
                ("description", models.TextField(blank=True, null=True)),
                (
                    "url",
                    models.CharField(blank=True, max_length=800, null=True),
                ),
                (
                    "config_schema",
                    django.contrib.postgres.fields.jsonb.JSONField(default=dict),
                ),
                ("tag", models.CharField(blank=True, max_length=200, null=True)),
                ("archive", models.BinaryField(blank=True, null=True)),
                ("from_json", models.BooleanField(default=False)),
                ("from_web", models.BooleanField(default=False)),
                (
                    "error",
                    django.contrib.postgres.fields.jsonb.JSONField(default=None, null=True),
                ),
            ],
        ),
        migrations.CreateModel(
            name="PluginConfig",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("enabled", models.BooleanField(default=False)),
                ("order", models.IntegerField(blank=True, null=True)),
                (
                    "config",
                    django.contrib.postgres.fields.jsonb.JSONField(default=dict),
                ),
                (
                    "error",
                    django.contrib.postgres.fields.jsonb.JSONField(default=None, null=True),
                ),
                (
                    "plugin",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="posthog.Plugin"),
                ),
                (
                    "team",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        to="posthog.Team",
                    ),
                ),
            ],
        ),
        migrations.AddField(
            model_name="team",
            name="plugins_opt_in",
            field=models.BooleanField(default=False),
        ),
    ]
