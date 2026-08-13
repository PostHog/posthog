from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("dashboards", "0018_validate_dashboard_group_constraints")]

    operations = [
        migrations.AddField(
            model_name="dashboardgroup",
            name="position",
            field=models.IntegerField(default=0),
        ),
        migrations.AlterField(
            model_name="dashboardgroup",
            name="name",
            field=models.CharField(blank=True, max_length=400, null=True),
        ),
        migrations.AlterModelOptions(
            name="dashboardgroup",
            options={
                "default_manager_name": "all_teams",
                "ordering": ["position", "created_at"],
            },
        ),
    ]
