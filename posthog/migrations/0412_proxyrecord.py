# Generated by Django 4.2.11 on 2024-05-15 08:23

from django.db import migrations, models
import django.db.models.deletion
import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0411_eventproperty_indexes"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProxyRecord",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.UUIDT, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("domain", models.CharField(max_length=64, unique=True)),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="proxy_records",
                        to="posthog.organization",
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
    ]
