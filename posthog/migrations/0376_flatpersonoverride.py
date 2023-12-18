# Generated by Django 3.2.19 on 2023-12-07 00:38

from django.db import migrations, models
import django.db.models.expressions


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0375_alter_survey_type"),
    ]

    operations = [
        migrations.CreateModel(
            name="FlatPersonOverride",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("team_id", models.BigIntegerField()),
                ("old_person_id", models.UUIDField()),
                ("override_person_id", models.UUIDField()),
                ("oldest_event", models.DateTimeField()),
                ("version", models.BigIntegerField(blank=True, null=True)),
            ],
        ),
        migrations.AddIndex(
            model_name="flatpersonoverride",
            index=models.Index(fields=["team_id", "override_person_id"], name="posthog_fla_team_id_224253_idx"),
        ),
        migrations.AddConstraint(
            model_name="flatpersonoverride",
            constraint=models.UniqueConstraint(
                fields=("team_id", "old_person_id"), name="flatpersonoverride_unique_old_person_by_team"
            ),
        ),
        migrations.AddConstraint(
            model_name="flatpersonoverride",
            constraint=models.CheckConstraint(
                check=models.Q(
                    ("old_person_id__exact", django.db.models.expressions.F("override_person_id")), _negated=True
                ),
                name="flatpersonoverride_check_circular_reference",
            ),
        ),
    ]
