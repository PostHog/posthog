import {
    parseURLFilters,
    parseURLVariables,
    SEARCH_PARAM_FILTERS_KEY,
    SEARCH_PARAM_QUERY_VARIABLES_KEY,
} from './dashboardUtils'

describe('parseURLVariables', () => {
    it('parses a JSON string value from search params', () => {
        const searchParams = {
            [SEARCH_PARAM_QUERY_VARIABLES_KEY]: '{"card_name":"Polukranos, Unchained"}',
        }
        const result = parseURLVariables(searchParams)
        expect(result).toEqual({ card_name: 'Polukranos, Unchained' })
    })

    it('handles an already-parsed object from search params (kea-router auto-parse)', () => {
        // When the URL has no trailing %20, kea-router auto-parses JSON values into objects
        const searchParams = {
            [SEARCH_PARAM_QUERY_VARIABLES_KEY]: { card_name: 'Polukranos, Unchained' },
        }
        const result = parseURLVariables(searchParams)
        expect(result).toEqual({ card_name: 'Polukranos, Unchained' })
    })

    it('returns empty object when key is missing', () => {
        expect(parseURLVariables({})).toEqual({})
    })

    it('returns empty object for invalid JSON string', () => {
        const searchParams = {
            [SEARCH_PARAM_QUERY_VARIABLES_KEY]: 'not-json',
        }
        expect(parseURLVariables(searchParams)).toEqual({})
    })
})

describe('parseURLFilters', () => {
    it('parses a JSON string value from search params', () => {
        const searchParams = {
            [SEARCH_PARAM_FILTERS_KEY]: '{"date_from":"-7d"}',
        }
        const result = parseURLFilters(searchParams)
        expect(result).toEqual({ date_from: '-7d' })
    })

    it('handles an already-parsed object from search params (kea-router auto-parse)', () => {
        const searchParams = {
            [SEARCH_PARAM_FILTERS_KEY]: { date_from: '-7d', date_to: 'now' },
        }
        const result = parseURLFilters(searchParams)
        expect(result).toEqual({ date_from: '-7d', date_to: 'now' })
    })

    it('returns empty object when key is missing', () => {
        expect(parseURLFilters({})).toEqual({})
    })
})
