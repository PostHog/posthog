from django.db import migrations, models

from posthog.migration_helpers import AddConstraintNotValid

# "llm_judge" is EvaluationType.LLM_JUDGE.value; see 0012 for why the literal is used here.
LLM_JUDGE = "llm_judge"


class Migration(migrations.Migration):
    dependencies = [
        ("ai_observability", "0012_clear_model_config_from_non_judge_evals"),
    ]

    operations = [
        # Enforce going forward: model_configuration may only be set on llm_judge evals. NOT VALID
        # skips the existing-row scan (0012 already cleaned it) but enforces on every new write
        # immediately. ValidateConstraint in 0014 scans the existing rows without blocking traffic.
        AddConstraintNotValid(
            model_name="evaluation",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("model_configuration__isnull", True),
                    ("evaluation_type", LLM_JUDGE),
                    _connector="OR",
                ),
                name="model_config_only_on_llm_judge",
            ),
        ),
    ]
