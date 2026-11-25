from django.db import migrations

# OpenAI shuts these models down on 2026-12-11. Judges still saved on them would fail every run after that.
RETIRED_MODELS = ("gpt-5", "gpt-5-mini", "gpt-5-nano")
REPLACEMENT_MODEL = "gpt-6-luna"


def move_judges_off_retired_models(apps, schema_editor):
    LLMModelConfiguration = apps.get_model("ai_observability", "LLMModelConfiguration")
    LLMModelConfiguration.objects.filter(provider="openai", model__in=RETIRED_MODELS).update(model=REPLACEMENT_MODEL)


class Migration(migrations.Migration):
    dependencies = [
        ("ai_observability", "0089_remove_tagger_state"),
    ]

    operations = [
        migrations.RunPython(move_judges_off_retired_models, migrations.RunPython.noop),
    ]
