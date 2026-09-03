from django.db import migrations

from posthog.migration_helpers import ValidateForeignKey


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1338_taggeditem_project_fk"),
    ]

    # VALIDATE scans under SHARE UPDATE EXCLUSIVE, so it does not block reads or writes.
    operations = [
        ValidateForeignKey(
            model_name="taggeditem",
            name="posthog_taggeditem_project_id_fk",
        ),
    ]
