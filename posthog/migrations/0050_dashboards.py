# Generated by Django 3.0.5 on 2020-05-07 09:12

from django.conf import settings
from django.db import migrations, models, transaction
import django.db.models.deletion


def forwards(apps, schema_editor):
    Team = apps.get_model("posthog", "Team")
    Dashboard = apps.get_model("posthog", "Dashboard")
    DashboardItem = apps.get_model("posthog", "DashboardItem")

    teams = Team.objects.all()
    for team in teams:
        with transaction.atomic():
            dashboard = Dashboard.objects.create(name="Default", pinned=True, team=team)

            items = DashboardItem.objects.filter(team=team)
            for item in items:
                item.dashboard = dashboard
                item.save()


def backwards(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0049_delete_funnelstep"),
    ]

    operations = [
        migrations.CreateModel(
            name="Dashboard",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID",),),
                ("name", models.CharField(blank=True, max_length=400, null=True)),
                ("pinned", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("deleted", models.BooleanField(default=False)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                ("team", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="posthog.Team"),),
            ],
        ),
        migrations.AddField(
            model_name="dashboarditem",
            name="dashboard",
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.CASCADE, related_name="items", to="posthog.Dashboard",
            ),
        ),
        migrations.RunPython(forwards, reverse_code=backwards, hints={"target_db": "default"}),
        migrations.AlterField(
            model_name="dashboarditem",
            name="dashboard",
            field=models.ForeignKey(
                null=False, on_delete=django.db.models.deletion.CASCADE, related_name="items", to="posthog.Dashboard",
            ),
        ),
    ]
