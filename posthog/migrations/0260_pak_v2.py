# Generated by Django 3.2.15 on 2022-09-20 17:07

from django.contrib.auth.hashers import get_hasher
from django.db import migrations, models

PERSONAL_API_KEY_SALT = "posthog_personal_api_key"


def hash_key_value(value: str) -> str:
    return get_hasher().encode(value, PERSONAL_API_KEY_SALT)


def hash_all_keys(apps, schema_editor):
    PersonalAPIKey = apps.get_model("posthog", "PersonalAPIKey")
    updated_instances = PersonalAPIKey.objects.all()
    for instance in updated_instances:
        instance.secure_value = hash_key_value(instance.value)
        instance.value = None
    PersonalAPIKey.objects.bulk_update(updated_instances, fields=["secure_value", "value"])


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0259_backfill_team_recording_domains"),
    ]

    operations = [
        migrations.AddField(
            model_name="personalapikey",
            name="secure_value",
            field=models.CharField(editable=False, max_length=300, null=True, unique=True),
        ),
        migrations.AlterField(
            model_name="personalapikey",
            name="value",
            field=models.CharField(blank=True, editable=False, max_length=50, null=True, unique=True),
        ),
        migrations.RunPython(hash_all_keys),
    ]
