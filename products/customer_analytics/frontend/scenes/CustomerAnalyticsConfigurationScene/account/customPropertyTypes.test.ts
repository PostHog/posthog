import type {
    CustomPropertyDisplayTypeEnumApi,
    CustomPropertySourceApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import {
    DISPLAY_TYPE_OPTIONS,
    formatCustomPropertyValue,
    isNumericDisplayType,
    labelForDisplayType,
    sourceSyncStatus,
} from './customPropertyTypes'

function definition(
    display_type: CustomPropertyDisplayTypeEnumApi,
    is_big_number = false
): { display_type: CustomPropertyDisplayTypeEnumApi; is_big_number: boolean } {
    return { display_type, is_big_number }
}

const buildSource = (overrides: Partial<CustomPropertySourceApi>): CustomPropertySourceApi =>
    ({
        is_enabled: true,
        last_sync_error: null,
        last_synced_at: '2026-01-01T00:00:00Z',
        ...overrides,
    }) as CustomPropertySourceApi

describe('customPropertyTypes', () => {
    it('labels each display type with its option label', () => {
        expect(labelForDisplayType('currency')).toBe('Currency')
        expect(labelForDisplayType('datetime')).toBe('Date & time')
        expect(labelForDisplayType('text')).toBe('Text')
        expect(labelForDisplayType('boolean')).toBe('True / false')
    })

    it('marks only numeric display types as numeric (drives the big-number switch)', () => {
        const numeric = DISPLAY_TYPE_OPTIONS.filter((option) => option.isNumeric).map((option) => option.value)
        expect(numeric).toEqual(['number', 'currency', 'percent'])
    })

    it('isNumericDisplayType matches the option metadata', () => {
        expect(isNumericDisplayType('currency')).toBe(true)
        expect(isNumericDisplayType('number')).toBe(true)
        expect(isNumericDisplayType('text')).toBe(false)
        expect(isNumericDisplayType('boolean')).toBe(false)
    })

    describe('formatCustomPropertyValue', () => {
        it('renders an em dash for missing values', () => {
            expect(formatCustomPropertyValue(null, definition('text'))).toBe('—')
            expect(formatCustomPropertyValue(undefined, definition('currency'))).toBe('—')
            expect(formatCustomPropertyValue('', definition('number'))).toBe('—')
        })

        it('formats currency, percent and numbers', () => {
            expect(formatCustomPropertyValue('1234.5', definition('currency'))).toBe('$1,234.50')
            expect(formatCustomPropertyValue('0.234', definition('percent'))).toBe('23.4%')
            expect(formatCustomPropertyValue('1234', definition('number'))).toBe('1,234')
        })

        it('abbreviates big numbers only when the definition opts in', () => {
            expect(formatCustomPropertyValue('12000', definition('number', true))).toBe('12K')
            expect(formatCustomPropertyValue('12000', definition('number', false))).toBe('12,000')
        })

        it('returns text and non-numeric input as-is', () => {
            expect(formatCustomPropertyValue('enterprise', definition('text'))).toBe('enterprise')
            expect(formatCustomPropertyValue('n/a', definition('number'))).toBe('n/a')
        })
    })

    it('derives sync status from the source state', () => {
        expect(sourceSyncStatus(buildSource({})).level).toBe('synced')
        expect(sourceSyncStatus(buildSource({ last_synced_at: null })).level).toBe('pending')
        expect(sourceSyncStatus(buildSource({ last_sync_error: 'boom' })).level).toBe('error')
    })

    it('shows the last error as the reason when a source is auto-disabled', () => {
        const status = sourceSyncStatus(buildSource({ is_enabled: false, last_sync_error: 'View not found' }))
        expect(status.level).toBe('disabled')
        expect(status.tooltip).toBe('View not found')
    })

    it('explains manual disabling when a disabled source has no error', () => {
        const status = sourceSyncStatus(buildSource({ is_enabled: false, last_sync_error: null }))
        expect(status.level).toBe('disabled')
        expect(status.tooltip).toBe('Syncing is turned off for this source.')
    })
})
