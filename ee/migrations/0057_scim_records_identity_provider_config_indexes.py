from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds can't run in a transaction, and PostHog policy keeps them in their
    # own migration away from regular DDL.
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
    ]
