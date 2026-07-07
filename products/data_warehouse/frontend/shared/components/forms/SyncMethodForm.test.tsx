import { ExternalDataSourceSyncSchema, IndexMechanism } from '~/types'

import { SyncTypeLabelMap } from '../../../utils'
import { getIndexWarningCopy, shouldOfferXmin } from './SyncMethodForm'

const baseSchema: ExternalDataSourceSyncSchema = {
    table: 'orders',
    should_sync: false,
    sync_time_of_day: null,
    incremental_field: null,
    incremental_field_type: null,
    sync_type: null,
    incremental_fields: [],
    incremental_available: false,
    append_available: false,
    supports_webhooks: false,
    should_sync_default: false,
    primary_key_columns: null,
    available_columns: [],
    detected_primary_keys: ['id'],
    xmin_available: true,
}

describe('SyncMethodForm', () => {
    it.each([
        ['flag on + available', { xmin_available: true }, true, true],
        ['flag off', { xmin_available: true }, false, false],
        ['not available', { xmin_available: false }, true, false],
        ['webhook-only table', { xmin_available: true, webhook_only: true }, true, false],
    ])('offers xmin: %s', (_, overrides, flagEnabled, expected) => {
        expect(shouldOfferXmin({ ...baseSchema, ...overrides }, flagEnabled)).toBe(expected)
    })

    it('exposes a label for the xmin sync type', () => {
        expect(SyncTypeLabelMap.xmin).toBe('xmin')
    })

    // Responses predating index_mechanism, or a mechanism added on the backend before this build
    // knows it, must fall back to the generic copy rather than rendering "No undefined detected".
    it.each([undefined, 'brand_new_mechanism' as IndexMechanism])(
        'index warning copy falls back to generic index advice for %s',
        (indexMechanism) => {
            expect(getIndexWarningCopy(indexMechanism)).toEqual({
                mechanism: 'index',
                suggestion: 'Consider adding an index',
            })
        }
    )
})
