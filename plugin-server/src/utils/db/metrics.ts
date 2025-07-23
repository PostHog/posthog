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
    buckets: [0, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, Infinity],
})
