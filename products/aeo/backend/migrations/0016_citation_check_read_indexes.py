from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("aeo", "0015_citation_check_names_brand"),
    ]

    operations = [
        migrations.AddField(
            model_name="aeocitationcheck",
            name="prompt_branded",
            field=models.BooleanField(
                blank=True,
                help_text="The prompt as it ran names one of the own brands, matched on whole words. Kept current by the own-citation reconcile. Null on checks recorded before it existed until that reconcile fills it.",
                null=True,
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="aeocitationcheck",
            index=models.Index(
                fields=["team_id", "created_at"],
                include=[
                    "id",
                    "mode",
                    "engine",
                    "prompt_id",
                    "prompt_topic",
                    "check_failed",
                    "cited",
                    "names_brand",
                    "prompt_branded",
                    "target_best_position",
                ],
                name="aeo_check_window_cover_idx",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="aeocitationcheck",
            index=models.Index(
                fields=["team_id", "prompt_id", "engine", "-created_at"],
                include=["id"],
                name="aeo_check_latest_idx",
            ),
        ),
    ]
