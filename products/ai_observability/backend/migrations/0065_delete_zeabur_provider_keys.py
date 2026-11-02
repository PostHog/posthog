from django.db import migrations
from django.utils import timezone


def delete_zeabur_provider_keys(apps, schema_editor):
    # Zeabur AI Hub shut down on Sep 22, 2026, so these keys can no longer reach a model.
    # Model configurations and evaluation configs point here with SET_NULL, so they keep their rows.
    LLMProviderKey = apps.get_model("ai_observability", "LLMProviderKey")
    Evaluation = apps.get_model("ai_observability", "Evaluation")

    # Without this, the next run disables these evals as provider_key_required and tells the
    # user to add a key, which cannot fix a provider that no longer exists.
    Evaluation.objects.filter(model_configuration__provider="zeabur", status="active", deleted=False).update(
        status="error",
        enabled=False,
        status_reason="model_not_found",
        status_reason_detail=(
            "Zeabur AI Hub was shut down and is no longer supported. "
            "Select a model from another provider, then re-enable this evaluation."
        ),
        updated_at=timezone.now(),
    )
    LLMProviderKey.objects.filter(provider="zeabur").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("ai_observability", "0064_backfill_execution_outcomes"),
    ]

    operations = [
        migrations.RunPython(delete_zeabur_provider_keys, migrations.RunPython.noop, elidable=True),
    ]
