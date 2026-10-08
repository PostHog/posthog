from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("dashboards", "0021_drop_dashboardtemplate_github_url_column"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[migrations.DeleteModel(name="DashboardSavedView")],
            database_operations=[],
        ),
    ]
