from django.db import migrations


def delete_zeabur_provider_keys(apps, schema_editor):
    # Zeabur AI Hub shut down on Sep 22, 2026, so these keys can no longer reach a model.
    # Model configurations and evaluation configs point here with SET_NULL, so they keep their rows.
    LLMProviderKey = apps.get_model("ai_observability", "LLMProviderKey")
    LLMProviderKey.objects.filter(provider="zeabur").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("ai_observability", "0064_backfill_execution_outcomes"),
    ]

    operations = [
        migrations.RunPython(delete_zeabur_provider_keys, migrations.RunPython.noop, elidable=True),
    ]
