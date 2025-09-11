# These have all been commented out to guarantee this runs
# properly on tests
# If we create these and shortly after run 0102 then we'll see
# some replica errors because we've barely created the tables
# and then immediately try to delete them which fails
operations: list = [
    # Drop tables/dictionaries to allow this to rerun
    # Dict first because it depends on the table
    # run_sql_with_exceptions(DROP_EXCHANGE_RATE_DICTIONARY_SQL()),
    # run_sql_with_exceptions(DROP_EXCHANGE_RATE_DICTIONARY_SQL(on_cluster=False), node_role=NodeRole.COORDINATOR),
    # run_sql_with_exceptions(DROP_EXCHANGE_RATE_TABLE_SQL()),
    # run_sql_with_exceptions(DROP_EXCHANGE_RATE_TABLE_SQL(on_cluster=False), node_role=NodeRole.COORDINATOR),
    # Recreate them all
    # run_sql_with_exceptions(EXCHANGE_RATE_TABLE_SQL()),
    # run_sql_with_exceptions(EXCHANGE_RATE_TABLE_SQL(on_cluster=False), node_role=NodeRole.COORDINATOR),
    # run_sql_with_exceptions(EXCHANGE_RATE_DATA_BACKFILL_SQL()),
    # run_sql_with_exceptions(EXCHANGE_RATE_DATA_BACKFILL_SQL(), node_role=NodeRole.COORDINATOR),
    # run_sql_with_exceptions(EXCHANGE_RATE_DICTIONARY_SQL()),
    # run_sql_with_exceptions(EXCHANGE_RATE_DICTIONARY_SQL(on_cluster=False), node_role=NodeRole.COORDINATOR),
]
