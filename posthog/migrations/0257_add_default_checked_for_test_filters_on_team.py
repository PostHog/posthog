# Generated by Django 3.2.14 on 2022-09-01 12:12

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0256_add_async_deletion_model"),
    ]

    operations = [
        migrations.AddField(
            model_name="team",
            name="test_account_filters_default_checked",
            field=models.BooleanField(blank=True, null=True),
        ),
    ]
