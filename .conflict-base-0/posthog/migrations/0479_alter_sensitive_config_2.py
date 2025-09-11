import json

from django.db import migrations


def re_encrypt_integrations(apps, schema_editor):
    for model in ["Integration"]:
        Model = apps.get_model("posthog", model)

        items = Model.objects.all()
        for item in items:
            if isinstance(item.sensitive_config, str):
                item.sensitive_config = json.loads(item.sensitive_config)
            item.save()


def backwards(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0478_migrate_encrypted_fields"),
    ]

    operations = [
        migrations.RunPython(re_encrypt_integrations, reverse_code=backwards, elidable=True),
    ]
