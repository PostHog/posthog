import { dayjs } from 'lib/dayjs'

import {
    parseURLFilters,
    parseURLVariables,
    SEARCH_PARAM_FILTERS_KEY,
    SEARCH_PARAM_QUERY_VARIABLES_KEY,
    scheduleSharedDashboardStaleAutoForceIfEligible,
    shouldSharedDashboardAutoForceForStaleTime,
} from './dashboardUtils'

async function flushMicrotasks(): Promise<void> {
    await new Promise<void>((resolve) => queueMicrotask(resolve))
}

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

describe('shouldSharedDashboardAutoForceForStaleTime', () => {
    it('returns false when last refresh is null', () => {
        expect(shouldSharedDashboardAutoForceForStaleTime(null)).toBe(false)
    })

    it('returns false when last refresh is an invalid Dayjs', () => {
        expect(shouldSharedDashboardAutoForceForStaleTime(dayjs(new Date(Number.NaN)))).toBe(false)
    })

    it('returns false when stalest tile is newer than the auto-force threshold', () => {
        expect(shouldSharedDashboardAutoForceForStaleTime(dayjs().subtract(59, 'minute'))).toBe(false)
    })

    it('returns true when stalest tile is older than the auto-force threshold', () => {
        expect(shouldSharedDashboardAutoForceForStaleTime(dayjs().subtract(61, 'minute'))).toBe(true)
    })

    describe('with fixed clock', () => {
        beforeEach(() => {
            jest.useFakeTimers()
            jest.setSystemTime(new Date('2026-06-15T12:00:00.000Z'))
        })

        afterEach(() => {
            jest.useRealTimers()
        })

        it('returns true at exactly the threshold age (60 minutes)', () => {
            expect(shouldSharedDashboardAutoForceForStaleTime(dayjs('2026-06-15T11:00:00.000Z'))).toBe(true)
        })

        it('returns false just under the threshold', () => {
            expect(shouldSharedDashboardAutoForceForStaleTime(dayjs('2026-06-15T11:01:00.000Z'))).toBe(false)
        })
    })
})

describe('scheduleSharedDashboardStaleAutoForceIfEligible', () => {
    it('does not invoke trigger when not stale', async () => {
        const trigger = jest.fn()
        scheduleSharedDashboardStaleAutoForceIfEligible({
            effectiveLastRefresh: dayjs().subtract(30, 'minute'),
            triggerDashboardRefresh: trigger,
        })
        await flushMicrotasks()
        expect(trigger).not.toHaveBeenCalled()
    })

    it('invokes trigger on the next microtask when stale', async () => {
        const trigger = jest.fn()
        scheduleSharedDashboardStaleAutoForceIfEligible({
            effectiveLastRefresh: dayjs().subtract(61, 'minute'),
            triggerDashboardRefresh: trigger,
        })
        expect(trigger).not.toHaveBeenCalled()
        await flushMicrotasks()
        expect(trigger).toHaveBeenCalledTimes(1)
    })
})
