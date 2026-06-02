import { ExternalDataSourceSyncSchema } from '~/types'

import { shouldShowCdcOption, shouldShowWebhookOption } from './SyncMethodForm'

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

describe('SyncMethodForm', () => {
    it('shows the webhook option when the schema is already on webhook mode even if no longer available', () => {
        expect(shouldShowWebhookOption({ ...baseSchema, sync_type: 'webhook', supports_webhooks: false })).toBe(true)
    })

    it('hides the webhook option when not supported and not the current mode', () => {
        expect(shouldShowWebhookOption({ ...baseSchema, sync_type: 'full_refresh', supports_webhooks: false })).toBe(
            false
        )
    })

    it('shows the webhook option when currently supported', () => {
        expect(shouldShowWebhookOption({ ...baseSchema, sync_type: null, supports_webhooks: true })).toBe(true)
    })

    it('shows the CDC option when the schema is already on CDC mode even if no longer available', () => {
        expect(shouldShowCdcOption({ ...baseSchema, sync_type: 'cdc', cdc_available: false })).toBe(true)
    })

    it('hides the CDC option when not available and not the current mode', () => {
        expect(shouldShowCdcOption({ ...baseSchema, sync_type: 'full_refresh', cdc_available: false })).toBe(false)
    })

    it('shows the CDC option when currently available', () => {
        expect(shouldShowCdcOption({ ...baseSchema, sync_type: null, cdc_available: true })).toBe(true)
    })
})
