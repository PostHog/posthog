import { Counter } from 'prom-client'

export const groupInfoCacheResultCounter = new Counter({
    name: 'group_info_cache_result',
    help: 'Group info cache result',
    labelNames: ['result'],
})

export const groupDataMissingCounter = new Counter({
    name: 'group_data_missing',
    help: 'Group data missing',
})

export const personUpdateVersionMismatchCounter = new Counter({
    name: 'person_update_version_mismatch',
    help: 'Person update version mismatch',
})

export const pluginLogEntryCounter = new Counter({
    name: 'plugin_log_entry',
    help: 'Plugin log entry created by plugin',
    labelNames: ['plugin_id', 'source'],
})
