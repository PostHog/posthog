from django.db import migrations

from posthog.migration_helpers import AddForeignKeyNotValid


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1457_personalapikey_provisioned_by"),
    ]

    # NOT VALID skips the scan of existing rows, so the lock this takes is a brief metadata change.
    operations = [
        AddForeignKeyNotValid(
            model_name="personalapikey",
            name="posthog_personalapikey_provisioned_by_id_fk",
            column="provisioned_by_id",
            to_table="posthog_oauthapplication",
            to_column="id",
        ),
    ]
