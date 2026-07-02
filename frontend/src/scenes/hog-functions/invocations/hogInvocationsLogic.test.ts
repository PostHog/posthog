import { searchParamsToFilters } from './hogInvocationsLogic'

describe('searchParamsToFilters', () => {
    // kea-router parses a duplicated `?inv_search=a&inv_search=b` into an array. Without
    // coercion `filters.search` is not a string and the later `.trim()` in the run/sparkline
    // loaders throws `t.search?.trim is not a function`, hard-crashing the Runs tab.
    it('coerces an array-valued search param to the last string', () => {
        const filters = searchParamsToFilters({ inv_search: ['a', 'b'] as unknown as string })
        expect(filters.search).toBe('b')
    })

    it('passes a plain string search param through unchanged', () => {
        const filters = searchParamsToFilters({ inv_search: 'abc' })
        expect(filters.search).toBe('abc')
    })
})
