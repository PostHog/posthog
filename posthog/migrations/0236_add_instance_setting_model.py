# Generated by Django 3.2.12 on 2022-05-18 12:39

import json
import logging
import pickle
from base64 import b64decode

from django.db import connection, migrations, models, utils

logger = logging.getLogger(__name__)


def populate_instance_settings(apps, schema_editor):
    try:
        InstanceSetting = apps.get_model("posthog", "InstanceSetting")
        with connection.cursor() as cursor:
            cursor.execute("SELECT key, value FROM constance_config")
            for key, pickled_value in cursor.fetchall():
                value = pickle.loads(b64decode(pickled_value.encode())) if pickled_value is not None else None
                InstanceSetting.objects.create(key=key, raw_value=json.dumps(value))
    except utils.ProgrammingError:
        logger.info("constance_config table did not exist, skipping populating posthog_instance_setting table")


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "0235_plugin_source_transpilation"),
    ]

    operations = [
        migrations.CreateModel(
            name="InstanceSetting",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("key", models.CharField(max_length=128)),
                ("raw_value", models.CharField(blank=True, max_length=1024)),
            ],
        ),
        migrations.AddConstraint(
            model_name="instancesetting",
            constraint=models.UniqueConstraint(fields=("key",), name="unique key"),
        ),
        migrations.RunPython(populate_instance_settings, migrations.RunPython.noop, elidable=True),
    ]
