import { ExternalDataSourceSyncSchema } from '~/types'

import { SyncTypeLabelMap } from '../../../utils'
import {
    getIncrementalSyncSupported,
    getSaveDisabledReason,
    looksCreationOnly,
    shouldOfferXmin,
} from './SyncMethodForm'

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
        ['available', { xmin_available: true }, true],
        ['not available', { xmin_available: false }, false],
        ['webhook-only table', { xmin_available: true, webhook_only: true }, false],
    ])('offers xmin: %s', (_, overrides, expected) => {
        expect(shouldOfferXmin({ ...baseSchema, ...overrides })).toBe(expected)
    })

    it('exposes a label for the xmin sync type', () => {
        expect(SyncTypeLabelMap.xmin).toBe('xmin')
    })

    it.each([
        ['no incremental support at all', { incremental_available: false }, false, true],
        ['no timestamp/numeric field to track', { incremental_fields: [] }, true, true],
        ['no primary key candidate', {}, false, true],
        ['a primary key candidate is available', {}, true, false],
    ])('incremental sync supported: %s', (_, overrides, hasPrimaryKeyCandidate, expectDisabled) => {
        const result = getIncrementalSyncSupported(
            { ...baseSchema, incremental_available: true, incremental_fields: [{} as any], ...overrides },
            hasPrimaryKeyCandidate
        )
        expect(result.disabled).toBe(expectDisabled)
    })

    it.each([
        [undefined, null, false, 'You must select a sync method before saving'],
        ['incremental', null, false, 'You must select an incremental field'],
        [
            'incremental',
            'updated_at',
            false,
            'Incremental replication requires a primary key. Select one below, or use full table replication instead',
        ],
        ['incremental', 'updated_at', true, undefined],
    ])(
        'save disabled reason for sync type %s: %s',
        (syncType, incrementalField, hasPrimaryKeyForIncremental, expected) => {
            expect(getSaveDisabledReason(syncType as any, incrementalField, null, hasPrimaryKeyForIncremental)).toBe(
                expected
            )
        }
    )

    it.each([
        ['created_at', true],
        ['added_at', true],
        ['inserted_on', true],
        ['created', true],
        ['updated_at', false],
        ['modified_at', false],
        ['id', false],
    ])('detects creation-only field names: %s', (fieldName, expected) => {
        expect(looksCreationOnly(fieldName)).toBe(expected)
    })
})
