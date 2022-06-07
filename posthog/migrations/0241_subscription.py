# Generated by Django 3.2.12 on 2022-06-07 14:18

from django.conf import settings
import django.contrib.postgres.fields
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0240_organizationinvite_message"),
    ]

    operations = [
        migrations.CreateModel(
            name="Subscription",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("target_type", models.CharField(choices=[("email", "Email")], max_length=10)),
                ("target_value", models.CharField(max_length=65535)),
                (
                    "frequency",
                    models.CharField(
                        choices=[
                            ("daily", "Daily"),
                            ("weekly", "Weekly"),
                            ("monthly", "Monthly"),
                            ("yearly", "Yearly"),
                        ],
                        max_length=10,
                    ),
                ),
                ("interval", models.IntegerField(default=1)),
                ("count", models.IntegerField(null=True)),
                (
                    "byweekday",
                    django.contrib.postgres.fields.ArrayField(
                        base_field=models.CharField(
                            choices=[
                                ("monday", "Monday"),
                                ("tuesday", "Tuesday"),
                                ("wednesday", "Wednesday"),
                                ("thursday", "Thursday"),
                                ("friday", "Friday"),
                                ("saturday", "Saturday"),
                                ("sunday", "Sunday"),
                            ],
                            max_length=10,
                        ),
                        blank=True,
                        default=None,
                        null=True,
                        size=None,
                    ),
                ),
                ("bysetpos", models.IntegerField(null=True)),
                ("start_date", models.DateTimeField()),
                ("until_date", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("deleted", models.BooleanField(default=False)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL
                    ),
                ),
                (
                    "dashboard",
                    models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to="posthog.dashboard"),
                ),
                (
                    "insight",
                    models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to="posthog.insight"),
                ),
                ("team", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="posthog.team")),
            ],
        ),
    ]
