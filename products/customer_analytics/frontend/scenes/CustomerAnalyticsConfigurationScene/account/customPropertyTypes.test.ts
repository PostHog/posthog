import type { CustomPropertyDisplayTypeEnumApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import {
    DISPLAY_TYPE_OPTIONS,
    formatCustomPropertyValue,
    isNumericDisplayType,
    labelForDisplayType,
} from './customPropertyTypes'

function definition(
    display_type: CustomPropertyDisplayTypeEnumApi,
    is_big_number = false
): { display_type: CustomPropertyDisplayTypeEnumApi; is_big_number: boolean } {
    return { display_type, is_big_number }
}

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
})
