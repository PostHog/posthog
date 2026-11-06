from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently, SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # CONCURRENTLY takes SHARE UPDATE EXCLUSIVE, so none of these block a reader or a writer, and
    # PostgreSQL cannot run them inside a transaction.
    atomic = False

    dependencies = [("ee", "0056_scim_records_organization_domain_nullable")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="scimprovisioneduser",
            index=models.Index(
                fields=["identity_provider_config", "username"],
                name="ee_scimprov_identit_3a28d7_idx",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="scimrequestlog",
            index=models.Index(
                fields=["identity_provider_config", "-created_at"],
                name="ee_scimrequ_identit_975d6d_idx",
            ),
        ),
        # The index behind the unique constraint 0059 attaches. Building it here rather than under
        # ADD CONSTRAINT is what keeps that constraint off the table's readers and writers.
        CreateIndexConcurrently(
            index_name="unique_user_identity_provider_config",
            table_name="ee_scimprovisioneduser",
            columns="(user_id, identity_provider_config_id)",
            unique=True,
        ),
    ]
