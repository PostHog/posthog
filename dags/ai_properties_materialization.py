import dagster

from dags.common import JobOwners
from dags.materialized_columns import run_materialize_mutations


@dagster.job(
    tags={
        "owner": JobOwners.TEAM_CLICKHOUSE.value,
        "description": "Materialize AI properties ($ai_*) into dedicated map column",
        "pr_reference": "https://github.com/PostHog/posthog/pull/32496",
    }
)
def materialize_ai_properties():
    """Manual job to materialize AI properties columns in ClickHouse.

    This materializes the AI properties map column added in PR #32496,
    which extracts properties with keys starting with '$ai_' into a
    dedicated map column for optimized querying.

    This job must be triggered manually and is not scheduled automatically.

    To run this job, use the following configuration in Dagster UI:

    ops:
      run_materialize_mutations:
        config:
          table: "sharded_events"
          columns:
            - "properties_group_ai"
          indexes:
            - "properties_group_ai_keys_bf"
            - "properties_group_ai_values_bf"
          partitions:
            lower: "202501"  # Adjust to your needs
            upper: "202512"  # Adjust to your needs
    """
    run_materialize_mutations()
