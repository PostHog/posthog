# Generated by Django 4.2.11 on 2024-05-29 17:24

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0418_pluginconfig_filters"),
    ]

    operations = [
        migrations.RunSQL(
            'ALTER TABLE "posthog_organization" DROP COLUMN "available_features" CASCADE -- drop-column-ignore',
            reverse_sql='ALTER TABLE "posthog_organization" ADD COLUMN "available_features" VARCHAR(64)[] DEFAULT array[]::varchar(64)[]',
            state_operations=[migrations.RemoveField("organization", "available_features")],
        )
    ]
