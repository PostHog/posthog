# Generated by Django 3.2.5 on 2022-02-14 14:28

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0207_cohort_count"),
    ]

    operations = [
        migrations.AlterField(
            model_name="plugin",
            name="updated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
