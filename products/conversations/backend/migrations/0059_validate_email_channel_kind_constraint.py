from django.db import migrations

from posthog.migration_helpers import ValidateConstraint


class Migration(migrations.Migration):
    dependencies = [
        ("conversations", "0058_add_email_channel_kind_constraint"),
    ]

    operations = [
        ValidateConstraint(model_name="emailchannel", name="email_channel_customer_not_default"),
        ValidateConstraint(model_name="emailchannel", name="email_channel_kind_owner"),
    ]
