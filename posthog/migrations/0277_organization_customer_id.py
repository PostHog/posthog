# Generated by Django 3.2.15 on 2022-11-08 10:05

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0276_organization_usage"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="customer_id",
            field=models.CharField(blank=True, max_length=200, null=True),
        ),
    ]
