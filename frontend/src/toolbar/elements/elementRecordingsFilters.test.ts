import { buildElementRecordingsFilters } from '~/toolbar/elements/elementRecordingsFilters'
import { PropertyFilterType, PropertyOperator } from '~/types'

describe('buildElementRecordingsFilters', () => {
    const commonFilters = { date_from: '-7d', date_to: null, filter_test_accounts: true }

    it.each([
        ['exact page', 'https://example.com/pricing', { value: 'https://example.com/pricing', operator: 'exact' }],
        ['wildcard page', 'https://example.com/*', { value: '^https\\:\\/\\/example\\.com\\/.*$', operator: 'regex' }],
    ])('narrows recordings to clicks on the element on the %s', (_name, wildcardHref, expectedUrlFilter) => {
        const filters = buildElementRecordingsFilters(
            'div.main > button.cta',
            'https://example.com/pricing',
            wildcardHref,
            commonFilters
        )

        expect(filters.date_from).toBe('-7d')
        expect(filters.filter_test_accounts).toBe(true)
        expect(filters.duration).toEqual([])

        const [event] = (filters.filter_group?.values[0] as any).values
        expect(event.id).toBe('$autocapture')
        expect(event.properties).toEqual([
            {
                key: '$current_url',
                value: expectedUrlFilter.value,
                operator: expectedUrlFilter.operator as PropertyOperator,
                type: PropertyFilterType.Event,
            },
            {
                key: 'selector',
                value: 'div.main > button.cta',
                operator: PropertyOperator.Exact,
                type: PropertyFilterType.Element,
            },
        ])
    })
})
