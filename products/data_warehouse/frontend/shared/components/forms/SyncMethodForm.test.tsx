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

    // Guards the full-refresh-append retention input: with the sub-mode on, a missing or non-positive
    // retention value must block save so we never PATCH an invalid config the backend would reject.
    it.each([
        ['append off, no value → allowed', false, null, undefined],
        ['append on, valid value → allowed', true, 3, undefined],
        ['append on, empty value → blocked', true, null, 'You must set how many snapshots (or days) to keep'],
        ['append on, zero value → blocked', true, 0, 'You must set how many snapshots (or days) to keep'],
        ['append on, over max → blocked', true, 366, 'Keep at most 365 snapshots (or days)'],
    ])('save disabled reason for full refresh: %s', (_, fullRefreshAppend, retentionValue, expected) => {
        expect(getSaveDisabledReason('full_refresh', null, null, fullRefreshAppend, retentionValue)).toBe(expected)
    })
})
