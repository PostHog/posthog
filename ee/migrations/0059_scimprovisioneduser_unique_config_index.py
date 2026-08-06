from django.db import migrations

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    # Building the unique index under ADD CONSTRAINT would hold ACCESS EXCLUSIVE for the length of
    # the build, and every read and write arriving behind it would wait. CONCURRENTLY takes SHARE
    # UPDATE EXCLUSIVE instead, which blocks neither; 0060 then promotes the finished index to the
    # constraint in a single catalog update. Concurrent builds can't run in a transaction.
    atomic = False

    dependencies = [("ee", "0058_backfill_scim_provisioned_user_config")]

    operations = [
        CreateIndexConcurrently(
            index_name="unique_user_identity_provider_config",
            table_name="ee_scimprovisioneduser",
            columns="(user_id, identity_provider_config_id)",
            unique=True,
        ),
    ]
