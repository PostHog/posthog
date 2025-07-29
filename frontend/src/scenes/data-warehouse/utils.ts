import { DatabaseSchemaField, DataVisualizationNode, NodeKind } from '~/queries/schema/schema-general'
import { DataWarehouseSyncInterval, ExternalDataSourceSyncSchema } from '~/types'

export const DATAWAREHOUSE_EDITOR_ITEM_ID = 'new-SQL'

export const defaultQuery = (table: string, columns: DatabaseSchemaField[]): DataVisualizationNode => {
    return {
        kind: NodeKind.DataVisualizationNode,
        source: {
            kind: NodeKind.HogQLQuery,
            // TODO: Use `hogql` tag?
            query: `SELECT ${columns
                .filter(({ table, fields, chain, schema_valid }) => !table && !fields && !chain && schema_valid)
                .map(({ name }) => name)} FROM ${table === 'numbers' ? 'numbers(0, 10)' : table} LIMIT 100`,
        },
    }
}

/**
 * This is meant to provide a human-readable sentence that computes the times of day in which a sync
 * will occur.
 * "The sync runs at 5:00 AM, 11:00 AM, 5:00 PM, and 11:00 PM UTC"
 * @param anchorTime - The time at which the sync was anchored (UTC)
 * @param syncFrequency - Interval at which the sync will reoccur
 */
export const syncAnchorIntervalToHumanReadable = (
    anchorTime: string,
    syncFrequency: DataWarehouseSyncInterval
): string => {
    // For intervals <= 1 hour, we don't use anchor time
    if (['5min', '30min', '1hour'].includes(syncFrequency)) {
        return `The sync runs every ${
            syncFrequency === '5min' ? '5 minutes' : syncFrequency === '30min' ? '30 minutes' : '1 hour'
        }`
    }

    const [hours, minutes] = anchorTime.split(':').map(Number)
    if (syncFrequency === '24hour') {
        return `The sync runs daily at ${humanTimeFormatter(hours, minutes)} UTC`
    }
    if (syncFrequency === '7day') {
        return `The sync runs weekly at ${humanTimeFormatter(hours, minutes)} UTC`
    }
    if (syncFrequency === '30day') {
        return `The sync runs monthly at ${humanTimeFormatter(hours, minutes)} UTC`
    }

    // by this point the syncFrequency should be in the format "6hour" or "12hour"
    const intervalMatch = syncFrequency.match(/\d+/)?.[0]
    if (!intervalMatch) {
        return ''
    }
    const interval = Number(intervalMatch)
    const syncTimes: string[] = []

    // get the first sync time
    let start = hours
    while (start >= interval) {
        start -= interval
    }
    for (let i = start; i < 24; i += interval) {
        syncTimes.push(humanTimeFormatter(i, minutes))
    }

    return `The sync runs at ${syncTimes.slice(0, -1).join(', ')}${syncTimes.length > 1 ? ' and ' : ''}${
        syncTimes[syncTimes.length - 1]
    } UTC`
}

function humanTimeFormatter(hours: number, minutes: number): string {
    const period = hours >= 12 ? 'PM' : 'AM'
    const displayHours = hours % 12 || 12 // Convert 0 to 12 for 12 AM
    return `${displayHours}:${minutes.toString().padStart(2, '0')} ${period}`
}

const typeSizes = {
    undefined: () => 0,
    boolean: () => 4,
    number: () => 8,
    string: (item: string) => 2 * item.length,
    object: (item: Record<any, any>) =>
        !item
            ? 0
            : Array.isArray(item)
            ? item.reduce((total, element) => sizeOfInBytes(element) + total, 0)
            : Object.keys(item).reduce((total, key) => sizeOfInBytes(key) + sizeOfInBytes(item[key]) + total, 0),
    function: () => 0,
    symbol: () => 0,
    bigint: () => 0,
}

export const sizeOfInBytes = (value: any): number => {
    return (typeSizes[typeof value] || (() => 0))(value)
}

export const SyncTypeLabelMap: Record<NonNullable<ExternalDataSourceSyncSchema['sync_type']>, string> = {
    full_refresh: 'Full refresh',
    incremental: 'Incremental',
    append: 'Append only',
}
