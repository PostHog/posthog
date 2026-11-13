from django.db import migrations

from posthog.migration_helpers import ValidateConstraint


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1422_oauth_device_grant"),
    ]

    operations = [
        ValidateConstraint(model_name="oauthapplication", name="enforce_supported_grant_types"),
    ]
