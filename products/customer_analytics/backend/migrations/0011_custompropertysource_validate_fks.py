from django.db import migrations

from posthog.migration_helpers import ValidateForeignKey


class Migration(migrations.Migration):
    dependencies = [
        ("customer_analytics", "0010_custompropertysource"),
    ]

    operations = [
        ValidateForeignKey(model_name="custompropertysource", name="custompropertysource_created_by_id_fk"),
        ValidateForeignKey(model_name="custompropertysource", name="custompropertysource_team_id_fk"),
    ]
