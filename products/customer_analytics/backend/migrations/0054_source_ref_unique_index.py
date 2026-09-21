from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    # CONCURRENTLY can't run inside a transaction.
    atomic = False

    dependencies = [
        ("customer_analytics", "0053_ownership_authority"),
    ]

    operations = [
        # Built concurrently so the relationship table stays writable while the index is created. The
        # next migration attaches it as the constraint Django's state declares.
        migrations.SeparateDatabaseAndState(
            state_operations=[],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="unique_relationship_per_source_ref",
                    table_name="customer_analytics_accountrelationship",
                    columns="(team_id, source, source_ref)",
                    unique=True,
                ),
            ],
        ),
        # A conditional UniqueConstraint is an index to Django, so the state matches the index as built.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="accountrelationshipdefinition",
                    constraint=models.UniqueConstraint(
                        condition=models.Q(("claim_saved_query__isnull", False)),
                        fields=("team", "claim_saved_query"),
                        name="unique_claim_view_per_definition",
                    ),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="unique_claim_view_per_definition",
                    table_name="customer_analytics_accountrelationshipdefinition",
                    columns="(team_id, claim_saved_query_id)",
                    unique=True,
                    where="WHERE claim_saved_query_id IS NOT NULL",
                ),
            ],
        ),
    ]
