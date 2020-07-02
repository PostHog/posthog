# Generated by Django 2.2.7 on 2020-01-27 19:31

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0009_auto_20200127_0018"),
    ]

    operations = [
        migrations.CreateModel(
            name="Funnel",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID",),),
                ("name", models.CharField(blank=True, max_length=400, null=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL,
                    ),
                ),
                ("team", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="posthog.Team"),),
            ],
        ),
        migrations.CreateModel(
            name="FunnelStep",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID",),),
                ("order", models.IntegerField()),
                ("action", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="posthog.Action"),),
                ("funnel", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="posthog.Funnel"),),
            ],
        ),
    ]
