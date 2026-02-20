import { initKeaTests } from '~/test/init'

import { dashboardFiltersLogic } from './dashboardFiltersLogic'
import { dashboardQueryCacheLogic, hashFilters } from './dashboardQueryCacheLogic'

describe('DashboardTileCard integration', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('reads from dashboardQueryCacheLogic when results are cached', () => {
        const filtersLogic = dashboardFiltersLogic({ id: 1 })
        filtersLogic.mount()
        const cacheLogic = dashboardQueryCacheLogic({ id: 1 })
        cacheLogic.mount()

        const hash = hashFilters({}, {})
        cacheLogic.actions.setCachedResult(100, hash, [{ count: 42 }])

        const result = cacheLogic.values.getCachedResult(100, {}, {})
        expect(result).toEqual([{ count: 42 }])
    })

    it('returns null from cache when no results are cached', () => {
        const filtersLogic = dashboardFiltersLogic({ id: 2 })
        filtersLogic.mount()
        const cacheLogic = dashboardQueryCacheLogic({ id: 2 })
        cacheLogic.mount()

        const result = cacheLogic.values.getCachedResult(100, {}, {})
        expect(result).toBeNull()
    })

    it('uses filter overrides from dashboardFiltersLogic', () => {
        const filtersLogic = dashboardFiltersLogic({ id: 3 })
        filtersLogic.mount()

        filtersLogic.actions.setPersistedFilters({ date_from: '-7d' })
        expect(filtersLogic.values.effectiveEditBarFilters).toMatchObject({ date_from: '-7d' })

        filtersLogic.actions.setDates('-30d', null)
        expect(filtersLogic.values.effectiveEditBarFilters).toMatchObject({ date_from: '-30d' })
    })

    it('cache result changes with different filter state', () => {
        const cacheLogic = dashboardQueryCacheLogic({ id: 4 })
        cacheLogic.mount()

        const hash7d = hashFilters({ date_from: '-7d' }, {})
        const hash30d = hashFilters({ date_from: '-30d' }, {})

        cacheLogic.actions.setCachedResult(100, hash7d, [{ count: 7 }])
        cacheLogic.actions.setCachedResult(100, hash30d, [{ count: 30 }])

        expect(cacheLogic.values.getCachedResult(100, { date_from: '-7d' }, {})).toEqual([{ count: 7 }])
        expect(cacheLogic.values.getCachedResult(100, { date_from: '-30d' }, {})).toEqual([{ count: 30 }])
    })

    it('DashboardTileCard can be imported without errors', async () => {
        const mod = await import('./DashboardTileCard')
        expect(mod.DashboardTileCard).toBeTruthy()
    })
})
