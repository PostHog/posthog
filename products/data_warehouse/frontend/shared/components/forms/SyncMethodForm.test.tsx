import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { ExternalDataSourceSyncSchema } from '~/types'

import { SyncTypeLabelMap } from '../../../utils'
import {
    SyncMethodForm,
    getIncrementalSyncSupported,
    getInitialRadioState,
    getSaveDisabledReason,
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

const SOURCE_CONFIGURATION_URL = '/project/1/data-warehouse/sources/managed-123/configuration'

describe('SyncMethodForm', () => {
    afterEach(cleanup)

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
        [
            'custom source points at the manifest',
            'Custom',
            "This table has no cursor in the source's manifest. Add one to sync it incrementally.",
        ],
        [
            'other sources keep the table-level reason',
            'Postgres',
            "Incremental replication isn't supported on this table. Use full table replication instead.",
        ],
    ])('explains a table without incremental support: %s', (_, sourceType, expected) => {
        expect(getIncrementalSyncSupported(baseSchema, sourceType)).toEqual({
            disabled: true,
            disabledReason: expected,
        })
    })

    it('sends a custom source to the manifest that turns incremental sync on', () => {
        render(
            <SyncMethodForm
                schema={baseSchema}
                sourceType="Custom"
                sourceConfigurationUrl={SOURCE_CONFIGURATION_URL}
                onClose={jest.fn()}
                onSave={jest.fn()}
            />
        )

        expect(screen.getByRole('link', { name: 'Open the source configuration' })).toHaveAttribute(
            'href',
            SOURCE_CONFIGURATION_URL
        )
    })

    it('leaves other sources without the manifest help', () => {
        render(
            <SyncMethodForm
                schema={baseSchema}
                sourceType="Postgres"
                sourceConfigurationUrl={SOURCE_CONFIGURATION_URL}
                onClose={jest.fn()}
                onSave={jest.fn()}
            />
        )

        expect(screen.queryByRole('link', { name: 'Open the source configuration' })).not.toBeInTheDocument()
    })

    it.each([
        ['key resolvable', true, 'incremental'],
        ['keyless with columns known', false, 'append'],
    ])('preselects incremental only when the key resolves: %s', (_, keyResolvable, expected) => {
        expect(getInitialRadioState({ ...baseSchema, xmin_available: false }, true, true, keyResolvable)).toBe(expected)
    })
})
