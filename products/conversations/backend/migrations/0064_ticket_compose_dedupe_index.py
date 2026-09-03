from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds cannot run inside a transaction; keep them in their own migration.
    atomic = False

    dependencies = [
        ("conversations", "0063_emailmessagemapping_full_body_plain"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="ticket",
            index=models.Index(
                models.F("team_id"),
                models.F("email_config_id"),
                models.F("email_from"),
                models.F("created_at").desc(),
                name="posthog_con_compose_dedupe_idx",
                condition=models.Q(channel_source="email"),
            ),
        ),
    ]
