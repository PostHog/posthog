# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ai_visibility", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="aivisibilityrun",
            name="progress_step",
            field=models.CharField(
                choices=[
                    ("starting", "Starting"),
                    ("extracting_info", "Extracting business info"),
                    ("generating_topics", "Generating topics"),
                    ("generating_prompts", "Generating prompts"),
                    ("running_ai_calls", "Running AI calls"),
                    ("combining_results", "Combining results"),
                    ("saving", "Saving results"),
                    ("complete", "Complete"),
                ],
                default="starting",
                help_text="Current step in the workflow for progress tracking",
                max_length=30,
            ),
        ),
    ]
