import { DISPLAY_TYPE_OPTIONS, isNumericDisplayType, labelForDisplayType } from './customPropertyTypes'

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
})
