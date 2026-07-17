from django.db import migrations

from posthog.migration_helpers import ValidateForeignKey


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1259_userpersonalization"),
    ]

    operations = [
        # Phase 2 of the NOT VALID foreign key added in 1259; the scan takes
        # only SHARE UPDATE EXCLUSIVE and the table is brand new, so this is
        # instant and never blocks posthog_user traffic.
        ValidateForeignKey(
            model_name="userpersonalization",
            name="posthog_userpersonalization_user_id_fk",
        ),
    ]
