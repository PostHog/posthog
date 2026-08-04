from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("posthog", "1286_comment_idempotency_key"),
    ]

    operations = [
        # Built concurrently: posthog_comment is large and shared across products. Partial,
        # because only callers opting into idempotency set the key and NULLs must still collide.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="comment",
                    constraint=models.UniqueConstraint(
                        condition=models.Q(("idempotency_key__isnull", False)),
                        fields=("team", "idempotency_key"),
                        name="posthog_comment_team_idem_key_uniq",
                    ),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="posthog_comment_team_idem_key_uniq",
                    table_name="posthog_comment",
                    columns="(team_id, idempotency_key)",
                    where="WHERE idempotency_key IS NOT NULL",
                    unique=True,
                ),
            ],
        ),
    ]
