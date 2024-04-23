from django.contrib.postgres.operations import ValidateConstraint
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0404_remove_propertydefinition_property_type_is_valid_and_more"),
    ]

    operations = [
        ValidateConstraint(model_name="propertydefinition", name="property_type_is_valid"),
    ]
