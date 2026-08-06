from django.db import migrations, models


class Migration(migrations.Migration):
    # One provisioning record per (user, SCIM tenant), the invariant `unique_user_organization_domain`
    # held while the tenant was a domain. The preceding backfill guarantees no row pair violates it.
    # ee_scimprovisioneduser holds one row per SCIM-provisioned user, so the index build behind
    # ADD CONSTRAINT is short enough not to need the concurrent dance.
    dependencies = [("ee", "0058_backfill_scim_provisioned_user_config")]

    operations = [
        migrations.AddConstraint(
            model_name="scimprovisioneduser",
            constraint=models.UniqueConstraint(
                fields=("user", "identity_provider_config"),
                name="unique_user_identity_provider_config",
            ),
        ),
    ]
