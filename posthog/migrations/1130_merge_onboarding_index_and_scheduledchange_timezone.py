# Merge migration: onboarding index chain (1127–1129) and provisioning/alert/scheduled chain (1122–1125).

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1129_onboarding_delegated_to_invite_index"),
        ("posthog", "1125_scheduledchange_timezone"),
    ]

    operations = []
