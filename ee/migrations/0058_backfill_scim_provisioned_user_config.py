from typing import Any

from django.db import migrations
from django.db.models import Count, OuterRef, Subquery

import structlog

logger = structlog.get_logger(__name__)

CHUNK_SIZE = 1000


def _ids_to_leave_on_their_domain_key(pending: Any) -> list[Any]:
    # One user provisioned through two domains of one config holds two records for what is now a
    # single tenant. Keep the oldest on the config and leave the rest on their domain key, so the
    # unique constraint added in 0060 holds without this dropping anyone's record.
    duplicate_groups = (
        pending.values("user_id", "organization_domain__identity_provider_config")
        .annotate(rows=Count("id"))
        .filter(rows__gt=1)
    )

    skipped: list[Any] = []
    for group in duplicate_groups:
        group_ids = list(
            pending.filter(
                user_id=group["user_id"],
                organization_domain__identity_provider_config=group["organization_domain__identity_provider_config"],
            )
            .order_by("created_at", "id")
            .values_list("id", flat=True)
        )
        for row_id in group_ids[1:]:
            logger.warning(
                "scim_provisioned_user_duplicate_for_identity_provider_config",
                scim_provisioned_user_id=str(row_id),
                identity_provider_config_id=str(group["organization_domain__identity_provider_config"]),
            )
        skipped.extend(group_ids[1:])
    return skipped


def backfill_scim_provisioned_user_config(apps: Any, schema_editor: Any) -> None:
    # Provisioning records are keyed by the SCIM tenant, which is now the IdP config rather than the
    # domain the endpoint used to be addressed by. Rows written before that move have to carry the
    # config too, otherwise SCIM sees an already-provisioned user as new and provisions them twice.
    #
    # This table holds one row per provisioned user per tenant, so it stays in the deploy: the
    # unique constraint two migrations later depends on it having run. Updates are set-based and
    # take row locks only — no reader or writer of the table waits on this.
    SCIMProvisionedUser = apps.get_model("ee", "SCIMProvisionedUser")
    OrganizationDomain = apps.get_model("posthog", "OrganizationDomain")
    db_alias = schema_editor.connection.alias

    pending = SCIMProvisionedUser.objects.using(db_alias).filter(
        identity_provider_config__isnull=True,
        organization_domain__identity_provider_config__isnull=False,
    )
    claimable = pending.exclude(id__in=_ids_to_leave_on_their_domain_key(pending))

    config_of_domain = Subquery(
        OrganizationDomain.objects.using(db_alias)
        .filter(pk=OuterRef("organization_domain_id"))
        .values("identity_provider_config_id")[:1]
    )

    # Walking the primary key keeps the scan forward-only and each statement small.
    last_id = None
    while True:
        batch_query = claimable.order_by("id")
        if last_id is not None:
            batch_query = batch_query.filter(id__gt=last_id)

        batch = list(batch_query.values_list("id", flat=True)[:CHUNK_SIZE])
        if not batch:
            break

        last_id = batch[-1]
        SCIMProvisionedUser.objects.using(db_alias).filter(id__in=batch).update(
            identity_provider_config=config_of_domain
        )


class Migration(migrations.Migration):
    dependencies = [("ee", "0057_scim_records_identity_provider_config_indexes")]

    operations = [
        migrations.RunPython(
            backfill_scim_provisioned_user_config,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
