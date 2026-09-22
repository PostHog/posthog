from django.db import migrations


class Migration(migrations.Migration):
    """Stop tracking cimd_metadata_url in Django state.

    client_id holds the same metadata-document URL since 1324, and no code resolves a CIMD
    client through this column any more.

    State-only: the column stays in Postgres so a rollback to the previous release still
    finds it, and so no read of a dropped column can 500 during the deploy window. Drop the
    column itself in a later release, once no deployed code references it.
    """

    dependencies = [("posthog", "1326_drop_legacy_provisioning_columns")]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name="oauthapplication",
                    name="cimd_metadata_url",
                ),
            ],
            database_operations=[],
        ),
    ]
