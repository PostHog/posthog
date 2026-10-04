import { PropertyFilterType, PropertyOperator } from '~/types'

import { normalizedModelPropertyFilter } from './modelBreakdown'

describe('normalizedModelPropertyFilter', () => {
    it('filters $ai_model with a case-insensitive regex', () => {
        expect(normalizedModelPropertyFilter('gpt-5')).toEqual({
            type: PropertyFilterType.Event,
            key: '$ai_model',
            operator: PropertyOperator.Regex,
            value: '(?i)(^|/)gpt-5$',
        })
    })

    it.each([
        ['gpt-4.1-mini', '(?i)(^|/)gpt-4\\.1-mini$'],
        ['gemini-2.5-pro-preview:large', '(?i)(^|/)gemini-2\\.5-pro-preview\\:large$'],
    ])('escapes the regex characters in %s so it cannot match a different model', (model, expected) => {
        expect(normalizedModelPropertyFilter(model).value).toBe(expected)
    })
})
