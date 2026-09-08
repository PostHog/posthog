from django.db import migrations

from posthog.migration_helpers import ValidateForeignKey


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1349_taggeditem_experiment_fk"),
    ]

    # VALIDATE scans under SHARE UPDATE EXCLUSIVE, so it does not block reads or writes.
    operations = [
        ValidateForeignKey(
            model_name="taggeditem",
            name="posthog_taggeditem_experiment_id_fk",
        ),
    ]
