import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ee", "0054_backfill_llm_playground_access_control"),
        ("posthog", "1226_identityproviderconfig_and_more"),
    ]

    operations = [
        # `db_index=False` keeps the column add from building a blocking index; the composite
        # indexes that serve config-scoped reads are built concurrently in 0057.
        migrations.AddField(
            model_name="scimprovisioneduser",
            name="identity_provider_config",
            field=models.ForeignKey(
                blank=True,
                db_index=False,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="scim_provisioned_users",
                to="posthog.identityproviderconfig",
            ),
        ),
        migrations.AddField(
            model_name="scimrequestlog",
            name="identity_provider_config",
            field=models.ForeignKey(
                blank=True,
                db_index=False,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="scim_request_logs",
                to="posthog.identityproviderconfig",
            ),
        ),
    ]
