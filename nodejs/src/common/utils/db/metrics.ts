import { Counter, Gauge, Histogram } from 'prom-client'

export const personUpdateVersionMismatchCounter = new Counter({
    name: 'person_update_version_mismatch',
    help: 'Person update version mismatch',
})

export const groupUpdateVersionMismatchCounter = new Counter({
    name: 'group_update_version_mismatch',
    help: 'Group update version mismatch',
    labelNames: ['type'],
})

export const pluginLogEntryCounter = new Counter({
    name: 'plugin_log_entry',
    help: 'Plugin log entry created by plugin',
    labelNames: ['plugin_id', 'source'],
})
export const moveDistinctIdsCountHistogram = new Histogram({
    name: 'move_distinct_ids_count',
    help: 'Number of distinct IDs moved in merge operations',
    buckets: [
        0, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000, 200000, 500000, 1000000,
    ],
})

export const personPropertiesSizeHistogram = new Histogram({
    name: 'person_properties_size',
    help: 'histogram of compressed person JSONB bytes retrieved in Person DB calls',
    labelNames: ['at'],
    buckets: [1024, 8192, 65536, 131072, 262144, 524288, 1048576, 2097152, 8388608],
})

export const postgresErrorCounter = new Counter({
    name: 'plugin_server_postgres_errors',
    help: 'Count of Postgres errors by type',
    labelNames: ['error_type', 'database_use'],
})

export const postgresPoolClientEventsCounter = new Counter({
    name: 'postgres_pool_client_events',
    help: 'node-postgres pool client lifecycle events, for measuring connection churn',
    labelNames: ['pool', 'event'],
})

export const postgresPoolAcquireDurationHistogram = new Histogram({
    name: 'postgres_pool_acquire_duration_seconds',
    help: 'Time spent waiting for a pooled client, which rises when the pool is saturated',
    labelNames: ['pool'],
    buckets: [0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1, 5, 10, 30, 60],
})

export const postgresClientErrorCounter = new Counter({
    name: 'postgres_client_errors',
    help: 'Errors raised on a checked-out client, labelled with the statement in flight',
    labelNames: ['pool', 'in_flight'],
})

export const postgresTransactionCounter = new Counter({
    name: 'postgres_transactions',
    help: 'Transaction outcomes',
    labelNames: ['pool', 'tag', 'outcome'],
})

export const postgresTransactionDurationHistogram = new Histogram({
    name: 'postgres_transaction_duration_seconds',
    help: 'Transaction duration by outcome',
    labelNames: ['pool', 'tag', 'outcome'],
    buckets: [0.001, 0.01, 0.05, 0.1, 0.5, 1, 5, 15, 30, 60, 300],
})

export const postgresOpenTransactionsGauge = new Gauge({
    name: 'postgres_open_transactions',
    help: 'Transactions currently holding a client; a floor above zero means they are leaking',
    labelNames: ['pool', 'tag'],
})

export const postgresLongOpenTransactionCounter = new Counter({
    name: 'postgres_long_open_transactions',
    help: 'Transactions past the slow-transaction threshold, by the statement they are stuck on',
    labelNames: ['pool', 'tag', 'in_flight'],
})

export const postgresOpenAtShutdownCounter = new Counter({
    name: 'postgres_transactions_open_at_shutdown',
    help: 'Transactions still open when the pools were told to close',
    labelNames: ['pool', 'tag'],
})

export const postgresClientRemovedInUseCounter = new Counter({
    name: 'postgres_client_removed_in_use',
    help: 'Pool removed a client while a transaction was still using it',
    labelNames: ['pool', 'tag', 'in_flight'],
})
