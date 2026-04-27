# Merge migration: parallel branches from 1123 (onboarding index vs provisioning backfill → 1124/1125).

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1124_onboarding_delegated_to_invite_index"),
        ("posthog", "1125_scheduledchange_timezone"),
    ]

    operations = []
