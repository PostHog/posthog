import {
    isTileDateRangeStale,
    parseURLFilters,
    parseURLVariables,
    SEARCH_PARAM_FILTERS_KEY,
    SEARCH_PARAM_QUERY_VARIABLES_KEY,
} from './dashboardUtils'

describe('parseURLVariables', () => {
    it.each([
        ['a JSON string value', '{"card_name":"Polukranos, Unchained"}', { card_name: 'Polukranos, Unchained' }],
        [
            'an already-parsed object (kea-router auto-parse)',
            { card_name: 'Polukranos, Unchained' },
            { card_name: 'Polukranos, Unchained' },
        ],
    ])('parses %s from search params', (_, input, expected) => {
        const result = parseURLVariables({ [SEARCH_PARAM_QUERY_VARIABLES_KEY]: input })
        expect(result).toEqual(expected)
    })

    it('returns empty object when key is missing', () => {
        expect(parseURLVariables({})).toEqual({})
    })

    it('returns empty object for invalid JSON string', () => {
        const consoleSpy = jest.spyOn(console, 'error').mockImplementation(() => {})
        const searchParams = {
            [SEARCH_PARAM_QUERY_VARIABLES_KEY]: 'not-json',
        }
        expect(parseURLVariables(searchParams)).toEqual({})
        consoleSpy.mockRestore()
    })
})

describe('parseURLFilters', () => {
    it.each([
        ['a JSON string value', '{"date_from":"-7d"}', { date_from: '-7d' }],
        [
            'an already-parsed object (kea-router auto-parse)',
            { date_from: '-7d', date_to: 'now' },
            { date_from: '-7d', date_to: 'now' },
        ],
    ])('parses %s from search params', (_, input, expected) => {
        const result = parseURLFilters({ [SEARCH_PARAM_FILTERS_KEY]: input })
        expect(result).toEqual(expected)
    })

    it('returns empty object when key is missing', () => {
        expect(parseURLFilters({})).toEqual({})
    })

    it('returns empty object for invalid JSON string', () => {
        const consoleSpy = jest.spyOn(console, 'error').mockImplementation(() => {})
        const searchParams = {
            [SEARCH_PARAM_FILTERS_KEY]: 'not-json',
        }
        expect(parseURLFilters(searchParams)).toEqual({})
        consoleSpy.mockRestore()
    })
})

describe('isTileDateRangeStale', () => {
    it('returns true when last_refresh is from a different calendar day', () => {
        const yesterday = new Date(Date.now() - 86400000).toISOString()
        expect(isTileDateRangeStale({ date_from: '-7d' }, yesterday, 'UTC')).toBe(true)
    })

    it('returns false when last_refresh is from today', () => {
        const justNow = new Date().toISOString()
        expect(isTileDateRangeStale({ date_from: '-7d' }, justNow, 'UTC')).toBe(false)
    })

    it('returns false for absolute date filters', () => {
        const yesterday = new Date(Date.now() - 86400000).toISOString()
        expect(isTileDateRangeStale({ date_from: '2024-01-15' }, yesterday, 'UTC')).toBe(false)
    })

    it('returns false for "all" date_from', () => {
        const yesterday = new Date(Date.now() - 86400000).toISOString()
        expect(isTileDateRangeStale({ date_from: 'all' }, yesterday, 'UTC')).toBe(false)
    })

    it('returns true when last_refresh is null', () => {
        expect(isTileDateRangeStale({ date_from: '-7d' }, null, 'UTC')).toBe(true)
    })

    it('returns false when no date_from in filters', () => {
        const yesterday = new Date(Date.now() - 86400000).toISOString()
        expect(isTileDateRangeStale({}, yesterday, 'UTC')).toBe(false)
    })

    it('returns true when last_refresh is from two days ago', () => {
        const twoDaysAgo = new Date(Date.now() - 2 * 86400000).toISOString()
        expect(isTileDateRangeStale({ date_from: '-7d' }, twoDaysAgo, 'UTC')).toBe(true)
    })
})
