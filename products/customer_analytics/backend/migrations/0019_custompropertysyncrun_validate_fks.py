from django.db import migrations

from posthog.migration_helpers import ValidateForeignKey


class Migration(migrations.Migration):
    dependencies = [
        ("customer_analytics", "0018_custompropertysyncrun"),
    ]

    operations = [
        ValidateForeignKey(model_name="custompropertysyncrun", name="custompropertysyncrun_created_by_id_fk"),
        ValidateForeignKey(model_name="custompropertysyncrun", name="custompropertysyncrun_team_id_fk"),
    ]
