import { initKeaTests } from '~/test/init'

import { dashboardQueryCacheLogic, hashFilters } from './dashboardQueryCacheLogic'

describe('dashboardQueryCacheLogic', () => {
    let logic: ReturnType<typeof dashboardQueryCacheLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = dashboardQueryCacheLogic({ id: 1 })
        logic.mount()
    })

    describe('setCachedResult', () => {
        it('stores and retrieves by insightId + filtersHash', () => {
            const filtersHash = hashFilters({ date_from: '-7d' }, {})
            logic.actions.setCachedResult(100, filtersHash, { data: [1, 2, 3] })

            const result = logic.values.getCachedResult(100, { date_from: '-7d' }, {})
            expect(result).toEqual({ data: [1, 2, 3] })
        })
    })

    describe('invalidateCache', () => {
        it('clears specific entries by insight ID', () => {
            const hash = hashFilters({}, {})
            logic.actions.setCachedResult(100, hash, { data: 'a' })
            logic.actions.setCachedResult(200, hash, { data: 'b' })

            logic.actions.invalidateCache([100])

            expect(logic.values.getCachedResult(100, {}, {})).toBeNull()
            expect(logic.values.getCachedResult(200, {}, {})).toEqual({ data: 'b' })
        })

        it('clears everything when no IDs specified', () => {
            const hash = hashFilters({}, {})
            logic.actions.setCachedResult(100, hash, { data: 'a' })
            logic.actions.setCachedResult(200, hash, { data: 'b' })

            logic.actions.invalidateCache()

            expect(logic.values.getCachedResult(100, {}, {})).toBeNull()
            expect(logic.values.getCachedResult(200, {}, {})).toBeNull()
        })
    })

    describe('cache eviction', () => {
        it('evicts oldest entry when cache exceeds MAX_CACHE_ENTRIES', () => {
            const hash = hashFilters({}, {})
            // Fill cache with 500 entries (the max)
            for (let i = 0; i < 500; i++) {
                logic.actions.setCachedResult(i, hash, { data: i })
            }
            // Entry 0 should still be there
            expect(logic.values.getCachedResult(0, {}, {})).toEqual({ data: 0 })

            // Adding one more should evict the oldest (entry 0)
            logic.actions.setCachedResult(500, hash, { data: 500 })
            expect(logic.values.getCachedResult(0, {}, {})).toBeNull()
            expect(logic.values.getCachedResult(500, {}, {})).toEqual({ data: 500 })
        })
    })

    describe('getCachedResult', () => {
        it('returns null on cache miss', () => {
            expect(logic.values.getCachedResult(999, {}, {})).toBeNull()
        })

        it('returns null when filters change (different hash)', () => {
            const hash = hashFilters({ date_from: '-7d' }, {})
            logic.actions.setCachedResult(100, hash, { data: [1, 2, 3] })

            const result = logic.values.getCachedResult(100, { date_from: '-30d' }, {})
            expect(result).toBeNull()
        })

        it('accounts for variable changes in hash', () => {
            const hash = hashFilters({}, { var1: { code_name: 'x', variableId: 'var1', value: '42' } })
            logic.actions.setCachedResult(100, hash, { data: 'with-var' })

            expect(
                logic.values.getCachedResult(100, {}, { var1: { code_name: 'x', variableId: 'var1', value: '42' } })
            ).toEqual({ data: 'with-var' })

            expect(
                logic.values.getCachedResult(100, {}, { var1: { code_name: 'x', variableId: 'var1', value: '99' } })
            ).toBeNull()
        })
    })
})
