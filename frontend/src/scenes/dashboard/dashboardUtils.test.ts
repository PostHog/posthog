import {
    parseURLFilters,
    parseURLVariables,
    SEARCH_PARAM_FILTERS_KEY,
    SEARCH_PARAM_QUERY_VARIABLES_KEY,
    snapshotDashboardFilterDates,
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

describe('snapshotDashboardFilterDates', () => {
    it('resolves relative date_from to absolute YYYY-MM-DD', () => {
        const result = snapshotDashboardFilterDates({ date_from: '-7d' }, 'UTC')
        expect(result.date_from).toMatch(/^\d{4}-\d{2}-\d{2}$/)
        expect(result.date_to).toBeUndefined()
    })

    it('resolves relative date_to to absolute YYYY-MM-DD', () => {
        const result = snapshotDashboardFilterDates({ date_from: '-7d', date_to: '-1d' }, 'UTC')
        expect(result.date_from).toMatch(/^\d{4}-\d{2}-\d{2}$/)
        expect(result.date_to).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    })

    it('does not modify already-absolute date strings', () => {
        const filters = { date_from: '2024-01-15', date_to: '2024-01-22' }
        const result = snapshotDashboardFilterDates(filters, 'UTC')
        expect(result.date_from).toBe('2024-01-15')
        expect(result.date_to).toBe('2024-01-22')
    })

    it('returns filters unchanged when no dates are set', () => {
        const filters = { properties: [] }
        const result = snapshotDashboardFilterDates(filters, 'UTC')
        expect(result).toEqual(filters)
    })

    it('does not resolve "all" date_from', () => {
        const filters = { date_from: 'all' }
        const result = snapshotDashboardFilterDates(filters, 'UTC')
        expect(result.date_from).toBe('all')
    })

    it('preserves other filter properties unchanged', () => {
        const result = snapshotDashboardFilterDates({ date_from: '-7d', date_to: null }, 'UTC')
        expect(result.date_from).toMatch(/^\d{4}-\d{2}-\d{2}$/)
        expect(result.date_to).toBeNull()
    })

    it('produces consistent results when called multiple times at the same moment', () => {
        const a = snapshotDashboardFilterDates({ date_from: '-7d' }, 'UTC')
        const b = snapshotDashboardFilterDates({ date_from: '-7d' }, 'UTC')
        expect(a.date_from).toBe(b.date_from)
    })
})
