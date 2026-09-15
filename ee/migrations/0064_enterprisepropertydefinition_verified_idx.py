from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("ee", "0063_scim_provisioned_user_config_set_null"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="enterprisepropertydefinition",
            index=models.Index(
                fields=["propertydefinition_ptr"],
                condition=models.Q(("verified", True)),
                name="ee_property_def_verified",
            ),
        ),
    ]
