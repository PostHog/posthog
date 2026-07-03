from django.db import migrations

from posthog.migration_helpers import ValidateConstraint


class Migration(migrations.Migration):
    dependencies = [
        ("ai_observability", "0013_add_model_config_only_on_llm_judge"),
    ]

    operations = [
        # Validate the cleaned existing rows under SHARE UPDATE EXCLUSIVE (does not block traffic).
        ValidateConstraint(model_name="evaluation", name="model_config_only_on_llm_judge"),
    ]
