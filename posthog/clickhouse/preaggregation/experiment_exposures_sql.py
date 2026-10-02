# Table for storing preaggregated experiment exposures
#
# Instead of scanning the events table on every experiment query to find
# who was exposed to which variant, we compute this once and store it here.
# Subsequent queries read from this table instead of scanning events.
#
# See posthog/hogql_queries/experiments/PREAGGREGATION.md for details.


TABLE_BASE_NAME = "experiment_exposures_preaggregated"


def DISTRIBUTED_EXPERIMENT_EXPOSURES_TABLE():
    return TABLE_BASE_NAME


def SHARDED_EXPERIMENT_EXPOSURES_TABLE():
    return f"sharded_{TABLE_BASE_NAME}"


def TRUNCATE_EXPERIMENT_EXPOSURES_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {SHARDED_EXPERIMENT_EXPOSURES_TABLE()}"
