# Generated by Django 4.2.14 on 2024-10-01 13:51

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0494_team_project_non_null"),
    ]

    operations = [
        migrations.AlterField(
            model_name="batchexportbackfill",
            name="start_at",
            field=models.DateTimeField(help_text="The start of the data interval.", null=True),
        ),
        migrations.AlterField(
            model_name="batchexportrun",
            name="data_interval_start",
            field=models.DateTimeField(help_text="The start of the data interval.", null=True),
        ),
    ]
