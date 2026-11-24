import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { nonFacetFilters, readFacets, withFacets } from './facetFilters'

const COUNTRY_FILTER: AnyPropertyFilter = {
    type: PropertyFilterType.Person,
    key: 'country',
    operator: PropertyOperator.Exact,
    value: ['DE'],
}

describe('facetFilters', () => {
    test.each([[['search']], [['web.search', 'get_weather']], [['a|b', 'c(d)', 'price$', '^start']]])(
        'reads back the tools it wrote: %j',
        (tools) => {
            expect(readFacets(withFacets([], { tools }, null)).tools).toEqual(tools)
        }
    )

    it('keeps the pill filters and the original slow threshold when a facet changes', () => {
        const slowAt2s = withFacets([COUNTRY_FILTER], { slow: true }, 2)
        const next = withFacets(slowAt2s, { models: ['gpt-4o'], errorsOnly: true }, 9)

        expect(readFacets(next)).toEqual({
            models: ['gpt-4o'],
            providers: [],
            tools: [],
            errorsOnly: true,
            slow: true,
        })
        expect(next).toContainEqual(expect.objectContaining({ key: '$ai_latency', value: 2 }))
        expect(nonFacetFilters(next)).toEqual([COUNTRY_FILTER])
    })
})
