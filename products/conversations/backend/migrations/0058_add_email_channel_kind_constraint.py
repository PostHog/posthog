from django.db import migrations, models

from posthog.migration_helpers import AddConstraintNotValid


class Migration(migrations.Migration):
    dependencies = [
        ("conversations", "0057_email_channel_kind_and_owner"),
    ]

    operations = [
        AddConstraintNotValid(
            model_name="emailchannel",
            constraint=models.CheckConstraint(
                condition=models.Q(kind="support") | models.Q(is_default=False),
                name="email_channel_customer_not_default",
            ),
        ),
        AddConstraintNotValid(
            model_name="emailchannel",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(kind="support", owner__isnull=True)
                    | models.Q(kind="customer_communication", owner__isnull=False)
                ),
                name="email_channel_kind_owner",
            ),
        ),
    ]
