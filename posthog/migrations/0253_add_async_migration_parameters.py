# Generated by Django 3.2.14 on 2022-07-13 10:38

from django.db import migrations, models


# :KLUDGE: Work around test_migrations_are_safe
class AddFieldNullSafe(migrations.AddField):
    def describe(self):
        return super().describe() + " -- not-null-ignore"


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0252_reset_insight_refreshing_status"),
    ]

    operations = [
        AddFieldNullSafe(
            model_name="asyncmigration",
            name="parameters",
            field=models.JSONField(default=dict),
        ),
    ]
