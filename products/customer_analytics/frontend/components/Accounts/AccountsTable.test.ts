import type {
    CustomPropertyDefinitionApi,
    CustomPropertySourceApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import { isCustomPropertyEditable, isCustomPropertyValueValid } from './AccountsTable'

const createCustomPropertySource = (): CustomPropertySourceApi => ({
    id: 'source-1',
    definition: 'custom-property-1',
    key_column: 'external_id',
    consecutive_failures: 0,
    last_synced_at: null,
    last_sync_error: null,
    created_at: '2026-01-01T00:00:00Z',
    created_by: null,
    updated_at: null,
    sync_frequency_interval_seconds: null,
    next_sync_at: null,
    latest_run: null,
    external_data_source: null,
    table_name: null,
    saved_query_name: null,
})

const createCustomPropertyDefinition = (
    overrides: Partial<CustomPropertyDefinitionApi> = {}
): CustomPropertyDefinitionApi => ({
    id: 'custom-property-1',
    name: 'Health score',
    display_type: 'number',
    is_canonical: false,
    source: null,
    has_workflow_reference: false,
    created_at: '2026-01-01T00:00:00Z',
    created_by: null,
    updated_at: null,
    references: [],
    ...overrides,
})

describe('isCustomPropertyEditable', () => {
    it.each([
        ['manual', createCustomPropertyDefinition(), true],
        ['canonical', createCustomPropertyDefinition({ is_canonical: true }), false],
        ['data warehouse managed', createCustomPropertyDefinition({ source: createCustomPropertySource() }), false],
        ['workflow managed', createCustomPropertyDefinition({ has_workflow_reference: true }), true],
    ])('marks %s definitions editable unless PostHog or the warehouse manages their values', (_, value, expected) => {
        expect(isCustomPropertyEditable(value)).toBe(expected)
    })
})

describe('isCustomPropertyValueValid', () => {
    it.each([
        ['accepts HTTP URLs', 'http://example.com', true],
        ['accepts HTTPS URLs', 'https://example.com', true],
        ['rejects a URL without a scheme', 'example.com', false],
        ['rejects unsupported URL schemes', 'ftp://example.com', false],
    ])('%s', (_, value, expected) => {
        expect(isCustomPropertyValueValid(value, createCustomPropertyDefinition({ display_type: 'link' }))).toBe(
            expected
        )
    })
})
