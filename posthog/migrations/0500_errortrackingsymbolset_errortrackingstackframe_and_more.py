# Generated by Django 4.2.15 on 2024-10-28 10:24

from django.db import migrations, models
import django.db.models.deletion
import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0499_hog_function_type"),
    ]

    operations = [
        migrations.CreateModel(
            name="ErrorTrackingSymbolSet",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.UUIDT, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("ref", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("storage_ptr", models.TextField(null=True)),
                ("team", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="posthog.team")),
            ],
        ),
        migrations.CreateModel(
            name="ErrorTrackingStackFrame",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.UUIDT, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("raw_id", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("contents", models.JSONField()),
                ("resolved", models.BooleanField()),
                (
                    "symbol_set",
                    models.ForeignKey(
                        null=True, on_delete=django.db.models.deletion.CASCADE, to="posthog.errortrackingsymbolset"
                    ),
                ),
                ("team", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="posthog.team")),
            ],
        ),
        migrations.AddIndex(
            model_name="errortrackingsymbolset",
            index=models.Index(fields=["team_id", "ref"], name="posthog_err_team_id_927574_idx"),
        ),
        migrations.AddConstraint(
            model_name="errortrackingsymbolset",
            constraint=models.UniqueConstraint(fields=("team_id", "ref"), name="unique_ref_per_team"),
        ),
        migrations.AddIndex(
            model_name="errortrackingstackframe",
            index=models.Index(fields=["team_id", "raw_id"], name="posthog_err_team_id_dc6a7f_idx"),
        ),
        migrations.AddConstraint(
            model_name="errortrackingstackframe",
            constraint=models.UniqueConstraint(fields=("team_id", "raw_id"), name="unique_raw_id_per_team"),
        ),
    ]
