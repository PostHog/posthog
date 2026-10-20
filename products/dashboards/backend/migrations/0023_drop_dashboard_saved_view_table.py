from django.db import migrations

from posthog.migration_helpers import SafeDropTable


class Migration(migrations.Migration):
    dependencies = [
        ("dashboards", "0022_remove_dashboardsavedview_from_state"),
    ]

    operations = [
        SafeDropTable("posthog_dashboard_saved_view"),
    ]
