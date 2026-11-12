import { ExternalDataSourceSchema } from '~/types'

type SyncType = ExternalDataSourceSchema['sync_type']
type CdcTableMode = ExternalDataSourceSchema['cdc_table_mode']

export function writesHistoryTable(syncType: SyncType, cdcTableMode: CdcTableMode): boolean {
    return (syncType === 'cdc' || syncType === 'incremental') && (cdcTableMode ?? 'consolidated') !== 'consolidated'
}

/** Whether saving this sync method stops writing the schema's history table. A save without a mode keeps the
 * saved one only on the same sync type: the API reports a schema that left CDC as consolidated. */
export function stopsWritingHistory(
    schema: Pick<ExternalDataSourceSchema, 'sync_type' | 'cdc_table_mode'>,
    syncType: SyncType,
    cdcTableMode: CdcTableMode | undefined
): boolean {
    const resultingMode = cdcTableMode ?? (syncType === schema.sync_type ? schema.cdc_table_mode : 'consolidated')
    return writesHistoryTable(schema.sync_type, schema.cdc_table_mode) && !writesHistoryTable(syncType, resultingMode)
}

/** A CDC table that keeps history reseeds it from the new snapshot; elsewhere a new mask can't reach past values. */
export function masksDropHistory(
    schema: Pick<ExternalDataSourceSchema, 'sync_type' | 'cdc_table_mode' | 'registered_history_table_name'>,
    newlyMasked: string[]
): boolean {
    return (
        newlyMasked.length > 0 &&
        !!schema.registered_history_table_name &&
        !(schema.sync_type === 'cdc' && writesHistoryTable(schema.sync_type, schema.cdc_table_mode))
    )
}
