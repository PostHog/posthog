# Generated by Django 3.1.12 on 2021-09-23 15:38

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0170_project_based_permissioning"),
    ]

    operations = [
        migrations.AddField(
            model_name="cohort", name="description", field=models.CharField(blank=True, max_length=1000),
        ),
    ]
