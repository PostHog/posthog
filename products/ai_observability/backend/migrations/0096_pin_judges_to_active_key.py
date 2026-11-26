from django.db import migrations

# The default model per provider when this migration was written. A judge with no model configuration
# runs on this model today, so pinning it to the same model keeps its results unchanged.
DEFAULT_MODEL_BY_PROVIDER = {
    "openai": "gpt-6-luna",
    "anthropic": "claude-haiku-4-5",
    "gemini": "gemini-2.5-flash",
}

BATCH_SIZE = 500


def pin_judges_to_active_key(apps, schema_editor):
    """Pin every LLM judge that runs on its project's active key to that key, so the fallback can be removed.

    A judge resolves to the active key when it has no model configuration, or when its configuration
    has no key and the same provider as the active key. Judges that cannot resolve today stay as they are.
    """
    EvaluationConfig = apps.get_model("ai_observability", "EvaluationConfig")
    Evaluation = apps.get_model("ai_observability", "Evaluation")
    LLMModelConfiguration = apps.get_model("ai_observability", "LLMModelConfiguration")

    configs = (
        EvaluationConfig.objects.filter(active_provider_key__isnull=False)
        .select_related("active_provider_key")
        .order_by("team_id")
    )
    for config in configs.iterator(chunk_size=BATCH_SIZE):
        key = config.active_provider_key
        judges = Evaluation.objects.filter(team_id=config.team_id, deleted=False, evaluation_type="llm_judge")

        LLMModelConfiguration.objects.filter(
            team_id=config.team_id,
            provider=key.provider,
            provider_key__isnull=True,
            evaluations__in=judges,
        ).update(provider_key=key)

        model = DEFAULT_MODEL_BY_PROVIDER.get(key.provider)
        if model is None:
            continue
        for judge in judges.filter(model_configuration__isnull=True).only("id"):
            model_configuration = LLMModelConfiguration.objects.create(
                team_id=config.team_id, provider=key.provider, model=model, provider_key=key
            )
            Evaluation.objects.filter(id=judge.id).update(model_configuration=model_configuration)


class Migration(migrations.Migration):
    dependencies = [
        ("ai_observability", "0095_experiment_score_history_index"),
    ]

    operations = [
        migrations.RunPython(pin_judges_to_active_key, migrations.RunPython.noop, elidable=True),
    ]
