from django.db import migrations

BATCH_SIZE = 500


def pin_judges_to_active_key(apps, schema_editor):
    """Pin every LLM judge that runs on its project's active key to that key, so the fallback can be removed.

    A judge resolves to the active key when it has no model configuration, or when its configuration
    has no key and the same provider as the active key. Judges that cannot resolve today stay as they are.
    """
    EvaluationConfig = apps.get_model("ai_observability", "EvaluationConfig")
    Evaluation = apps.get_model("ai_observability", "Evaluation")
    LLMModelConfiguration = apps.get_model("ai_observability", "LLMModelConfiguration")
    # bin/migrate can run on a different connection than the default one.
    db = schema_editor.connection.alias

    configs = (
        EvaluationConfig.objects.using(db)
        .filter(active_provider_key__isnull=False)
        .select_related("active_provider_key")
        .order_by("team_id")
    )
    for config in configs.iterator(chunk_size=BATCH_SIZE):
        key = config.active_provider_key
        judges = Evaluation.objects.using(db).filter(team_id=config.team_id, deleted=False, evaluation_type="llm_judge")

        LLMModelConfiguration.objects.using(db).filter(
            team_id=config.team_id,
            provider=key.provider,
            provider_key__isnull=True,
            evaluations__in=judges,
        ).update(provider_key=key)

        # A judge with no model configuration runs on the provider's current default, so it gets pinned to that
        # model. Imported here so a fresh database, which has no configs, never loads app code.
        from products.ai_observability.backend.llm import DEFAULT_MODEL_BY_PROVIDER

        model = DEFAULT_MODEL_BY_PROVIDER.get(key.provider)
        if model is None:
            continue
        for judge in judges.filter(model_configuration__isnull=True).only("id"):
            model_configuration = LLMModelConfiguration.objects.using(db).create(
                team_id=config.team_id, provider=key.provider, model=model, provider_key=key
            )
            # Someone may have picked a model for this judge, or turned it into a code check, since it was read,
            # so only fill the empty slot of a judge that is still one.
            pinned = (
                Evaluation.objects.using(db)
                .filter(id=judge.id, model_configuration__isnull=True, evaluation_type="llm_judge", deleted=False)
                .update(model_configuration=model_configuration)
            )
            if not pinned:
                model_configuration.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("ai_observability", "0095_experiment_score_history_index"),
    ]

    operations = [
        migrations.RunPython(pin_judges_to_active_key, migrations.RunPython.noop, elidable=True),
    ]
