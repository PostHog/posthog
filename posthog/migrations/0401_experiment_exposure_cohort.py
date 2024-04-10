# Generated by Django 4.1.13 on 2024-04-10 16:20

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0400_datawarehousetable_row_count"),
    ]

    operations = [
        migrations.AddField(
            model_name="experiment",
            name="exposure_cohort",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to="posthog.cohort"),
        ),
    ]
