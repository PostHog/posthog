from django.conf import settings
from django.db import migrations

# "llm_judge" is EvaluationType.LLM_JUDGE.value. Use the literal here: historical models from
# apps.get_model() don't carry the Python enum, and Django serializes the enum to this string anyway.
LLM_JUDGE = "llm_judge"


def clear_model_config_from_non_judge_evals(apps, schema_editor):
    """Detach model_configuration from evals that should never have one, then delete the orphans.

    Only llm_judge evals use a model_configuration / BYOK provider key. Hog and sentiment evals
    acquired one through the provider-key `assign` endpoint, whose legacy-eval branch created a
    config for every passed eval without filtering on type. The save() guard added afterwards then
    rejected every write to those evals, locking them out of all edits. This clears the bad state so
    the CHECK constraint (added in the next migration) can validate, and unblocks the affected evals.

    Validated against production (2026-06-30) before writing, both regions:
      - Violating rows (evaluation_type <> 'llm_judge' AND model_configuration_id IS NOT NULL):
          US: 45 (33 live + 12 deleted), all evaluation_type='hog'
          EU: 11 (all live),             all evaluation_type='hog'
          0 sentiment rows in either region.
      - Distinct configs referenced by those evals: US 45, EU 11 (1:1 with the evals).
      - Configs also referenced by a legitimate llm_judge eval: 0 in both regions — so every
        detached config becomes a true orphan and is safe to delete. The evaluations__isnull and
        taggers__isnull guards below still protect any config shared with an eval or a tagger
        (Tagger also FKs LLMModelConfiguration), so a config is deleted only when nothing else
        references it. No llm_judge eval is touched: exclude() filters them out entirely.
    ~56 rows updated + ~56 deleted total; a single UPDATE and DELETE hold locks only momentarily,
    matching the "tiny affected set" reasoning in 0007_retire_reports_for_deleted_evaluations.

    The migration is atomic (default), so a retry (bin/migrate re-runs the whole migration on
    failure) redoes detach+delete together rather than leaving detached-but-undeleted configs behind.
    """
    Evaluation = apps.get_model("ai_observability", "Evaluation")
    LLMModelConfiguration = apps.get_model("ai_observability", "LLMModelConfiguration")

    violating = Evaluation.objects.exclude(evaluation_type=LLM_JUDGE).filter(model_configuration__isnull=False)
    orphaned_config_ids = list(violating.values_list("model_configuration_id", flat=True))
    violating.update(model_configuration=None)
    LLMModelConfiguration.objects.filter(
        id__in=orphaned_config_ids, evaluations__isnull=True, taggers__isnull=True
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("ai_observability", "0011_evaluation_target"),
        ("posthog", "1245_duckgres_sink_schema_state"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(clear_model_config_from_non_judge_evals, migrations.RunPython.noop),
    ]
