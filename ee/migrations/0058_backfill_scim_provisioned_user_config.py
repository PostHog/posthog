from typing import Any

from django.db import migrations

import structlog

logger = structlog.get_logger(__name__)

CHUNK_SIZE = 500


def backfill_scim_provisioned_user_config(apps: Any, schema_editor: Any) -> None:
    # Provisioning records are keyed by the SCIM tenant, which is now the IdP config rather than the
    # domain the endpoint used to be addressed by. Rows written before that move have to carry the
    # config too, otherwise SCIM sees an already-provisioned user as new and provisions them twice.
    SCIMProvisionedUser = apps.get_model("ee", "SCIMProvisionedUser")
    db_alias = schema_editor.connection.alias

    stale_rows = (
        SCIMProvisionedUser.objects.using(db_alias)
        .filter(
            identity_provider_config__isnull=True,
            organization_domain__identity_provider_config__isnull=False,
        )
        .values_list("id", "user_id", "organization_domain__identity_provider_config")
    )

    for row_id, user_id, config_id in stale_rows.iterator(chunk_size=CHUNK_SIZE):
        # A user provisioned through two domains that share one config has two rows for what is now
        # a single tenant. Keep the first on the config and leave the rest on their legacy key, so
        # the unique constraint added in 0059 holds without dropping any row.
        if (
            SCIMProvisionedUser.objects.using(db_alias)
            .filter(user_id=user_id, identity_provider_config_id=config_id)
            .exists()
        ):
            logger.warning(
                "scim_provisioned_user_duplicate_for_identity_provider_config",
                scim_provisioned_user_id=str(row_id),
                identity_provider_config_id=str(config_id),
            )
            continue

        SCIMProvisionedUser.objects.using(db_alias).filter(pk=row_id).update(identity_provider_config_id=config_id)


class Migration(migrations.Migration):
    dependencies = [("ee", "0057_scim_records_identity_provider_config_indexes")]

    operations = [
        migrations.RunPython(
            backfill_scim_provisioned_user_config,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
