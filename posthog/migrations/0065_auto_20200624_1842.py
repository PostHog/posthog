# Generated by Django 3.0.6 on 2020-06-24 18:42

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0064_toolbar_mode"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="action",
            index=models.Index(fields=["team_id", "-updated_at"], name="posthog_act_team_id_8c04de_idx"),
        ),
    ]
