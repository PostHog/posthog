import { ExternalDataSourceSchema } from '~/types'

import { masksDropHistory, stopsWritingHistory } from './historyTable'

type SyncType = ExternalDataSourceSchema['sync_type']
type Mode = ExternalDataSourceSchema['cdc_table_mode']

describe('historyTable', () => {
    test.each<[string, SyncType, Mode, SyncType, Mode | undefined, boolean]>([
        ['cdc history turned off', 'cdc', 'both', 'cdc', 'consolidated', true],
        ['cdc keeps history', 'cdc', 'both', 'cdc', 'both', false],
        ['incremental save without a mode', 'incremental', 'both', 'incremental', undefined, false],
        ['cdc to incremental without a mode', 'cdc', 'both', 'incremental', undefined, true],
        ['cdc to incremental keeping history', 'cdc', 'both', 'incremental', 'both', false],
        ['no history before', 'incremental', 'consolidated', 'full_refresh', undefined, false],
    ])('stopsWritingHistory: %s', (_name, savedSyncType, savedMode, syncType, mode, expected) => {
        expect(stopsWritingHistory({ sync_type: savedSyncType, cdc_table_mode: savedMode }, syncType, mode)).toBe(
            expected
        )
    })

    test.each<[string, SyncType, Mode, string | null, string[], boolean]>([
        ['incremental keeping history', 'incremental', 'both', 'orders_history', ['email'], true],
        ['cdc keeping history reseeds it', 'cdc', 'both', 'orders_history', ['email'], false],
        ['cdc with a leftover history table', 'cdc', 'consolidated', 'orders_cdc', ['email'], true],
        ['no history table', 'incremental', 'consolidated', null, ['email'], false],
        ['no new mask', 'incremental', 'both', 'orders_history', [], false],
    ])('masksDropHistory: %s', (_name, syncType, mode, historyTableName, newlyMasked, expected) => {
        expect(
            masksDropHistory(
                { sync_type: syncType, cdc_table_mode: mode, registered_history_table_name: historyTableName },
                newlyMasked
            )
        ).toBe(expected)
    })
})
