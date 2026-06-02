import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { ExternalDataSourceSyncSchema } from '~/types'

import { SyncMethodForm } from './SyncMethodForm'

const baseSchema: ExternalDataSourceSyncSchema = {
    table: 'charges',
    should_sync: true,
    sync_time_of_day: null,
    incremental_field: null,
    incremental_field_type: null,
    sync_type: null,
    incremental_fields: [],
    incremental_available: false,
    append_available: false,
    supports_webhooks: false,
    should_sync_default: true,
    primary_key_columns: null,
    available_columns: [],
    detected_primary_keys: null,
}

const renderForm = (schema: ExternalDataSourceSyncSchema): void => {
    render(<SyncMethodForm schema={schema} onClose={() => {}} onSave={() => {}} />)
}

describe('SyncMethodForm', () => {
    afterEach(() => cleanup())

    it('shows the webhook option when the schema is already on webhook mode even if no longer available', () => {
        renderForm({ ...baseSchema, sync_type: 'webhook', supports_webhooks: false })

        expect(screen.getByRole('heading', { name: 'Webhook' })).toBeInTheDocument()
    })

    it('hides the webhook option when not supported and not the current mode', () => {
        renderForm({ ...baseSchema, sync_type: 'full_refresh', supports_webhooks: false })

        expect(screen.queryByRole('heading', { name: 'Webhook' })).not.toBeInTheDocument()
    })

    it('shows the webhook option when currently supported', () => {
        renderForm({ ...baseSchema, sync_type: null, supports_webhooks: true })

        expect(screen.getByRole('heading', { name: 'Webhook' })).toBeInTheDocument()
    })

    it('shows the CDC option when the schema is already on CDC mode even if no longer available', () => {
        renderForm({ ...baseSchema, sync_type: 'cdc', cdc_available: false })

        expect(screen.getByRole('heading', { name: 'CDC (change data capture)' })).toBeInTheDocument()
    })

    it('hides the CDC option when not available and not the current mode', () => {
        renderForm({ ...baseSchema, sync_type: 'full_refresh', cdc_available: false })

        expect(screen.queryByRole('heading', { name: 'CDC (change data capture)' })).not.toBeInTheDocument()
    })
})
