from django.db import migrations

from posthog.migration_helpers import ValidateForeignKey


class Migration(migrations.Migration):
    dependencies = [
        ("customer_analytics", "0015_eventstream_eventstreammember"),
    ]

    operations = [
        ValidateForeignKey(model_name="eventstream", name="eventstream_team_id_fk"),
        ValidateForeignKey(model_name="eventstream", name="eventstream_created_by_id_fk"),
        ValidateForeignKey(model_name="eventstreammember", name="eventstreammember_team_id_fk"),
        ValidateForeignKey(model_name="eventstreammember", name="eventstreammember_created_by_id_fk"),
    ]
