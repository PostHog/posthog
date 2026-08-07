import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    # `on_delete` lives in Django, not the schema: this changes model state only and emits no SQL,
    # so it takes no lock. Confirmed with sqlmigrate.

    dependencies = [
        ("ee", "0060_scimprovisioneduser_unique_config"),
        ("posthog", "1294_identityproviderconfig_saml_relay_state_unique"),
    ]

    operations = [
        migrations.AlterField(
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
