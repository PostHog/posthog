# Generated by Django 3.2.5 on 2022-02-14 15:42

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0207_cohort_count"),
    ]

    operations = [
        migrations.AddField(model_name="cohort", name="count", field=models.IntegerField(blank=True, null=True),),
    ]
