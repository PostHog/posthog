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
    it.each<[string, ExternalDataSourceSyncSchema['sync_type'], boolean, boolean]>([
        ['already on webhook mode, no longer available', 'webhook', false, true],
        ['not supported and not the current mode', 'full_refresh', false, false],
        ['currently supported', null, true, true],
    ])('shouldShowWebhookOption: %s', (_name, sync_type, supports_webhooks, expected) => {
        expect(shouldShowWebhookOption({ ...baseSchema, sync_type, supports_webhooks })).toBe(expected)
    })

    it.each<[string, ExternalDataSourceSyncSchema['sync_type'], boolean, boolean]>([
        ['already on CDC mode, no longer available', 'cdc', false, true],
        ['not available and not the current mode', 'full_refresh', false, false],
        ['currently available', null, true, true],
    ])('shouldShowCdcOption: %s', (_name, sync_type, cdc_available, expected) => {
        expect(shouldShowCdcOption({ ...baseSchema, sync_type, cdc_available })).toBe(expected)
    })
})
