from django.db import migrations

from posthog.migration_helpers import untrack_field


class Migration(migrations.Migration):
    dependencies = [
        ("dashboards", "0019_alter_buttontile_created_by_alter_buttontile_team_and_more"),
    ]

    operations = [
        untrack_field("dashboardtemplate", "github_url"),
    ]
