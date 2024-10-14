# Generated by Django 4.2.15 on 2024-10-14 18:21

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0487_team_survey_config"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="is_active",
            field=models.BooleanField(
                default=True, help_text="Unselect this to temporarily disable an account.", verbose_name="active"
            ),
        ),
    ]
