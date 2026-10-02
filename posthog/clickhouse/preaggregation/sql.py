# These tables are used to save and re-use intermediate results from queries

# They are hidden behind a flag that is only visible behind a HogQLQueryModifier that is only settable in the query debugger

# One unsolved problem so far is ensuring that we can read our own writes, as often we write to this table immediately before we want to re-read the results.
# Some ideas for how to solve this in a future version:
# * write to the sharded tables rather than the distributed tables, with more control over which node run both the preagg and combiner query
# * try various clickhouse settings like select_sequential_consistency, insert_quorum_parallel, insert_quorum

# Given that this is not accessible by real customers, we can merge this before we solve this issue, and we can experiment with settings later


TABLE_BASE_NAME = "preaggregation_results"


def DISTRIBUTED_PREAGGREGATION_RESULTS_TABLE():
    return TABLE_BASE_NAME


def SHARDED_PREAGGREGATION_RESULTS_TABLE():
    return f"sharded_{TABLE_BASE_NAME}"
