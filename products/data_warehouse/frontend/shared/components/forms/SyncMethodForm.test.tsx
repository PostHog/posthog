import { ExternalDataSourceSyncSchema } from '~/types'

import { SyncTypeLabelMap } from '../../../utils'
import { getSaveDisabledReason, shouldOfferXmin } from './SyncMethodForm'

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

    // Retention 0 is valid (plain overwrite full refresh); a non-integer or out-of-range value blocks
    // save so we never PATCH a config the backend (an integer field, max 365) would reject.
    const RETENTION_RANGE_MSG = 'Snapshot retention must be a whole number between 0 and 365'
    it.each([
        ['zero → allowed (overwrite)', 0, undefined],
        ['positive → allowed', 3, undefined],
        ['at max → allowed', 365, undefined],
        ['over max → blocked', 366, RETENTION_RANGE_MSG],
        ['fractional → blocked', 3.5, RETENTION_RANGE_MSG],
        ['negative → blocked', -1, RETENTION_RANGE_MSG],
    ])('save disabled reason for full refresh: %s', (_, retentionValue, expected) => {
        expect(getSaveDisabledReason('full_refresh', null, null, retentionValue)).toBe(expected)
    })
})
