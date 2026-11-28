from django.db import migrations


def share_existing_keys(apps, schema_editor):
    # Every key before 0099 was added under the admin-only rule, so all of them stay usable by everyone.
    LLMProviderKey = apps.get_model("ai_observability", "LLMProviderKey")
    LLMProviderKey.objects.using(schema_editor.connection.alias).update(shared=True)


class Migration(migrations.Migration):
    dependencies = [
        ("ai_observability", "0099_llmproviderkey_shared"),
    ]

    operations = [
        migrations.RunPython(share_existing_keys, migrations.RunPython.noop, elidable=True),
    ]
