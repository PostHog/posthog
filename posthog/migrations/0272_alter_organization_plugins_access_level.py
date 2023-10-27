# Generated by Django 3.2.15 on 2022-10-18 06:42

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0271_delete_promptsequencestate"),
    ]

    # NOTE: This is basically a no-op as the default logic is all in runtime anyway
    operations = [
        migrations.AlterField(
            model_name="organization",
            name="plugins_access_level",
            field=models.PositiveSmallIntegerField(
                choices=[(0, "none"), (3, "config"), (6, "install"), (9, "root")],
                default=3,
            ),
        ),
    ]
