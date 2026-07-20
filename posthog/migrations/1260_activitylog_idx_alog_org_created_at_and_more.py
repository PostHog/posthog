from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # posthog_activitylog is large and write-heavy, so build the B-trees CONCURRENTLY to
    # avoid an ACCESS EXCLUSIVE lock on the table. Concurrent builds can't run in a
    # transaction, hence atomic = False. SafeAddIndexConcurrently disables
    # lock_timeout/statement_timeout, skips an already-valid index, and rebuilds an invalid
    # leftover from an interrupted build, so a cancelled deploy doesn't wedge bin/migrate
    # retries. It tracks Django model state itself — no SeparateDatabaseAndState wrapper.
    atomic = False

    dependencies = [
        ("posthog", "1259_globalratelimitthresholdconfig"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="activitylog",
            index=models.Index(
                fields=["organization_id", "-created_at"],
                name="idx_alog_org_created_at",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="activitylog",
            index=models.Index(
                fields=["team_id", "-created_at"],
                name="idx_alog_team_created_at",
            ),
        ),
    ]
