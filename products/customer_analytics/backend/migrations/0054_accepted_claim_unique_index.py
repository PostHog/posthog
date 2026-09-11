from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    # CONCURRENTLY can't run inside a transaction.
    atomic = False

    dependencies = [
        ("customer_analytics", "0053_ownership_authority"),
    ]

    operations = [
        # Built concurrently so the relationship table stays writable while the index is created;
        # `SeparateDatabaseAndState` keeps the model's UniqueConstraint in Django's state.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="accountrelationship",
                    constraint=models.UniqueConstraint(
                        condition=models.Q(("source", "salesforce_claim")),
                        fields=("team", "source_ref"),
                        name="unique_accepted_claim_per_task",
                    ),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="unique_accepted_claim_per_task",
                    table_name="customer_analytics_accountrelationship",
                    columns="(team_id, source_ref)",
                    unique=True,
                    where="WHERE source = 'salesforce_claim'",
                ),
            ],
        ),
    ]
