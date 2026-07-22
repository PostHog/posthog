from django.db import migrations

from posthog.migration_helpers import ValidateForeignKey


class Migration(migrations.Migration):
    dependencies = [
        ("customer_analytics", "0016_announcement"),
    ]

    operations = [
        ValidateForeignKey(model_name="announcement", name="ca_announcement_team_id_fk"),
        ValidateForeignKey(model_name="announcement", name="ca_announcement_created_by_id_fk"),
        ValidateForeignKey(model_name="announcementdelivery", name="ca_announcement_delivery_team_id_fk"),
    ]
