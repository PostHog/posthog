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
    buckets: [
        0, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000, 200000, 500000, 1000000,
    ],
})

export const moveDistinctIdsDurationHistogram = new Histogram({
    name: 'move_distinct_ids_duration_seconds',
    help: 'Wall time of the UPDATE that moves distinct IDs in a merge, by number of rows moved',
    labelNames: ['rows'],
    buckets: [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60],
})

const MOVED_ROWS_BANDS: [number, string][] = [
    [0, '0'],
    [1, '1'],
    [10, '2-10'],
    [100, '11-100'],
    [1000, '101-1000'],
    [10000, '1001-10000'],
]

export function movedRowsBand(count: number): string {
    for (const [upperBound, band] of MOVED_ROWS_BANDS) {
        if (count <= upperBound) {
            return band
        }
    }
    return '10001+'
}

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
