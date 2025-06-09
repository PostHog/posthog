import { Counter } from 'prom-client'

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
