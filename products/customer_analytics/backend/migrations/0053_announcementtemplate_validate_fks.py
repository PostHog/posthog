from django.db import migrations

from posthog.migration_helpers import ValidateForeignKey


class Migration(migrations.Migration):
    dependencies = [
        ("customer_analytics", "0052_announcementtemplate"),
    ]

    operations = [
        ValidateForeignKey(model_name="announcementtemplate", name="ca_ann_template_team_id_fk"),
        ValidateForeignKey(model_name="announcementtemplate", name="ca_ann_template_created_by_id_fk"),
    ]
