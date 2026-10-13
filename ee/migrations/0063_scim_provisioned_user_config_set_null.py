from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ee", "0062_squash_2026_09_07_schema_addons"),
    ]

    operations = [
        migrations.AlterField(
            model_name="scimprovisioneduser",
            name="identity_provider_config",
            field=models.ForeignKey(
                blank=True,
                db_index=False,
                null=True,
                on_delete=models.SET_NULL,
                related_name="scim_provisioned_users",
                to="posthog.identityproviderconfig",
            ),
        ),
    ]
