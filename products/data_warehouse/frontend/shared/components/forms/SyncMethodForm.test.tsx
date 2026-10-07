import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { ExternalDataSourceSyncSchema } from '~/types'

import { SyncTypeLabelMap } from '../../../utils'
import { SyncMethodForm, getInitialRadioState, getSaveDisabledReason, shouldOfferXmin } from './SyncMethodForm'

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
        ['no key, key required', null, true, 'Select primary key columns, or use full table replication instead'],
        ['no key, source declares its own key', null, false, undefined],
        ['key picked, key required', ['id'], true, undefined],
    ])('requires a merge key for incremental: %s', (_, mergeKey, keyRequired, expected) => {
        expect(getSaveDisabledReason('incremental', 'updated_at', null, mergeKey, keyRequired)).toBe(expected)
    })

    it.each([
        ['key resolvable', true, 'incremental'],
        ['keyless with columns known', false, 'append'],
    ])('preselects incremental only when the key resolves: %s', (_, keyResolvable, expected) => {
        expect(getInitialRadioState({ ...baseSchema, xmin_available: false }, true, true, keyResolvable)).toBe(expected)
    })

    describe('primary key picker', () => {
        afterEach(cleanup)

        // The API refuses an incremental switch without a merge key whenever it knows the
        // schema's columns. Discovery returning none must not hide the picker that sets one,
        // or the refusal has no remedy.
        it('offers the stored columns when discovery returned none', () => {
            render(
                <SyncMethodForm
                    schema={{
                        ...baseSchema,
                        sync_type: 'incremental',
                        incremental_available: true,
                        incremental_field: 'updated_at',
                        incremental_fields: [
                            { field: 'updated_at', field_type: 'datetime', label: 'updated_at', type: 'datetime' },
                        ],
                        detected_primary_keys: null,
                        available_columns: [{ field: 'order_id', label: 'order_id', type: 'bigint', nullable: false }],
                    }}
                    availableColumns={[]}
                    primaryKeyDetectionSupported
                    onClose={() => {}}
                    onSave={() => {}}
                />
            )

            expect(screen.getByText(/select one or more columns to use as the primary key/i)).toBeInTheDocument()
        })
    })
})
