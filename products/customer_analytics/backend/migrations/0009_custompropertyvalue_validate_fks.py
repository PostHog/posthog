from django.db import migrations

from posthog.migration_helpers import ValidateForeignKey


class Migration(migrations.Migration):
    dependencies = [
        ("customer_analytics", "0008_custom_property_value"),
    ]

    operations = [
        ValidateForeignKey(model_name="custompropertyvalue", name="custompropertyvalue_created_by_id_fk"),
        ValidateForeignKey(model_name="custompropertyvalue", name="custompropertyvalue_team_id_fk"),
    ]
