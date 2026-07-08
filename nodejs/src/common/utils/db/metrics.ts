import { Counter, Histogram } from 'prom-client'

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
    buckets: [0, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000],
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
