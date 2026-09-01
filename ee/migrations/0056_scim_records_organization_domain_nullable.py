import django.db.models.deletion
from django.db import migrations, models

# SCIM records are keyed by IdP config now, so nothing fills `organization_domain` on new rows.
# Django's own AlterField for a NOT NULL drop rebuilds the column's foreign key, which revalidates
# every existing row while holding a lock — on ee_scimrequestlog that is the whole request history.
# The catalog flip alone is what's needed, so run it as SQL and leave AlterField to model state.
# Dropping NOT NULL on its own is a catalog update: no table scan, no row rewrite.
DROP_NOT_NULL = [
    migrations.RunSQL(
        sql=f'ALTER TABLE "{table}" ALTER COLUMN "organization_domain_id" DROP NOT NULL;',
        reverse_sql=f'ALTER TABLE "{table}" ALTER COLUMN "organization_domain_id" SET NOT NULL;',
    )
    for table in ("ee_scimprovisioneduser", "ee_scimrequestlog")
]


class Migration(migrations.Migration):
    dependencies = [("ee", "0055_scim_records_identity_provider_config")]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="scimprovisioneduser",
                    name="organization_domain",
                    field=models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="scim_provisioned_users",
                        to="posthog.organizationdomain",
                    ),
                ),
                migrations.AlterField(
                    model_name="scimrequestlog",
                    name="organization_domain",
                    field=models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="scim_request_logs",
                        to="posthog.organizationdomain",
                    ),
                ),
            ],
            database_operations=DROP_NOT_NULL,
        ),
    ]
