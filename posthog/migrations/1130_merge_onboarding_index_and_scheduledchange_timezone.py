# Merge migration: onboarding, scheduled changes, and DuckLake branches.

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1129_onboarding_delegated_to_invite_index"),
        ("posthog", "1125_scheduledchange_timezone"),
        ("posthog", "1126_ducklake_make_team_nullable_require_owner"),
    ]

    operations = []
