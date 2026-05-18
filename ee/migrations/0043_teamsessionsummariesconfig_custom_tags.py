from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ee", "0042_team_session_summaries_config"),
    ]

    operations = [
        migrations.AddField(
            model_name="teamsessionsummariesconfig",
            name="custom_tags",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text=(
                    "Team-defined tags layered on top of the fixed taxonomy. Stored as a "
                    "{name: description} mapping matching the AI_TAGS_FIXED_TAXONOMY shape. "
                    "Names must be lowercase snake_case. Descriptions tell the LLM when to "
                    "apply each tag."
                ),
            ),
        ),
    ]
