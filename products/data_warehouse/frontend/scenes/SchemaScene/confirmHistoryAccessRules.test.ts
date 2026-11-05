import { ExternalDataSourceSchema } from '~/types'

import { turnsHistoryOn } from './confirmHistoryAccessRules'

type Mode = ExternalDataSourceSchema['cdc_table_mode']

describe('turnsHistoryOn', () => {
    it.each<[string, ExternalDataSourceSchema['sync_type'], Mode, Mode, boolean]>([
        ['consolidated to both', 'cdc', 'consolidated', 'both', true],
        ['consolidated to cdc_only', 'cdc', 'consolidated', 'cdc_only', true],
        ['incremental to cdc with history', 'incremental', undefined, 'both', true],
        ['cdc_only to both', 'cdc', 'cdc_only', 'both', false],
        ['both to consolidated', 'cdc', 'both', 'consolidated', false],
    ])('%s', (_name, savedSyncType, savedMode, newMode, expected) => {
        expect(turnsHistoryOn({ sync_type: savedSyncType, cdc_table_mode: savedMode }, 'cdc', newMode)).toBe(expected)
    })
})
