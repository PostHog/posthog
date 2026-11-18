from django.db import migrations

from posthog.migration_helpers import ValidateConstraint


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1446_user_kind_optional_email"),
    ]

    operations = [
        ValidateConstraint(model_name="user", name="posthog_user_human_has_email"),
    ]
