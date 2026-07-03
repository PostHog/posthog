# Draft skill references on a revision. Additive nullable-default JSONB column
# on the agent_platform product DB (not a hot table) — `db_default` lands a real
# Postgres default so non-Django writers and the test-schema path stay happy.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("agent_platform", "0010_remove_is_preview_state_only"),
    ]

    operations = [
        migrations.AddField(
            model_name="agentrevision",
            name="skill_refs",
            field=models.JSONField(db_default=models.Value("[]"), default=list),
        ),
    ]
