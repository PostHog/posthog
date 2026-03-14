import { initKeaTests } from '~/test/init'

import {
    MAX_RECENT_FILTERS,
    RECENT_FILTER_MAX_AGE_MS,
    recentTaxonomicFiltersLogic,
} from './recentTaxonomicFiltersLogic'
import { TaxonomicFilterGroupType } from './types'

describe('recentTaxonomicFiltersLogic', () => {
    let logic: ReturnType<typeof recentTaxonomicFiltersLogic.build>

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        logic = recentTaxonomicFiltersLogic
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('starts with an empty list', () => {
        expect(logic.values.recentFilters).toEqual([])
    })

    it('records a selection with groupType, value, item, and timestamp', () => {
        const item = { name: '$pageview', id: 'uuid-1' }
        logic.actions.recordRecentFilter(TaxonomicFilterGroupType.Events, '$pageview', item)

        const filters = logic.values.recentFilters
        expect(filters).toHaveLength(1)
        expect(filters[0]).toEqual(
            expect.objectContaining({
                groupType: TaxonomicFilterGroupType.Events,
                value: '$pageview',
                item,
            })
        )
        expect(typeof filters[0].timestamp).toBe('number')
    })

    it('prepends new entries so most recent is first', () => {
        logic.actions.recordRecentFilter(TaxonomicFilterGroupType.Events, 'first', { name: 'first' })
        logic.actions.recordRecentFilter(TaxonomicFilterGroupType.Events, 'second', { name: 'second' })

        expect(logic.values.recentFilters[0].value).toBe('second')
        expect(logic.values.recentFilters[1].value).toBe('first')
    })

    it('deduplicates by groupType + value, keeping the most recent', () => {
        logic.actions.recordRecentFilter(TaxonomicFilterGroupType.Events, '$pageview', { name: '$pageview' })
        logic.actions.recordRecentFilter(TaxonomicFilterGroupType.Events, '$click', { name: '$click' })
        logic.actions.recordRecentFilter(TaxonomicFilterGroupType.Events, '$pageview', {
            name: '$pageview',
            updated: true,
        })

        const filters = logic.values.recentFilters
        expect(filters).toHaveLength(2)
        expect(filters[0].value).toBe('$pageview')
        expect(filters[0].item).toEqual({ name: '$pageview', updated: true })
        expect(filters[1].value).toBe('$click')
    })

    it('allows the same value in different group types', () => {
        logic.actions.recordRecentFilter(TaxonomicFilterGroupType.Events, 'name', { name: 'name' })
        logic.actions.recordRecentFilter(TaxonomicFilterGroupType.PersonProperties, 'name', { name: 'name' })

        expect(logic.values.recentFilters).toHaveLength(2)
    })

    it(`caps entries at ${MAX_RECENT_FILTERS}`, () => {
        for (let i = 0; i < MAX_RECENT_FILTERS + 5; i++) {
            logic.actions.recordRecentFilter(TaxonomicFilterGroupType.Events, `event-${i}`, { name: `event-${i}` })
        }

        expect(logic.values.recentFilters).toHaveLength(MAX_RECENT_FILTERS)
        expect(logic.values.recentFilters[0].value).toBe(`event-${MAX_RECENT_FILTERS + 4}`)
    })

    it('drops entries older than 30 days on next write', () => {
        jest.useFakeTimers()
        try {
            logic.actions.recordRecentFilter(TaxonomicFilterGroupType.Events, 'old-event', { name: 'old-event' })
            expect(logic.values.recentFilters).toHaveLength(1)

            jest.advanceTimersByTime(RECENT_FILTER_MAX_AGE_MS + 1000)

            logic.actions.recordRecentFilter(TaxonomicFilterGroupType.Events, 'new-event', { name: 'new-event' })

            const filters = logic.values.recentFilters
            expect(filters.every((f) => f.value !== 'old-event')).toBe(true)
            expect(filters[0].value).toBe('new-event')
        } finally {
            jest.useRealTimers()
        }
    })

    it.each([
        {
            groupType: TaxonomicFilterGroupType.HogQLExpression,
            description: 'HogQLExpression',
        },
        {
            groupType: TaxonomicFilterGroupType.SuggestedFilters,
            description: 'SuggestedFilters',
        },
        {
            groupType: TaxonomicFilterGroupType.RecentFilters,
            description: 'RecentFilters',
        },
        {
            groupType: TaxonomicFilterGroupType.Empty,
            description: 'Empty',
        },
        {
            groupType: TaxonomicFilterGroupType.Wildcards,
            description: 'Wildcards',
        },
    ])('ignores selections from excluded group type: $description', ({ groupType }) => {
        logic.actions.recordRecentFilter(groupType, 'some-value', { name: 'some-value' })
        expect(logic.values.recentFilters).toHaveLength(0)
    })

    it('ignores selections with null value', () => {
        logic.actions.recordRecentFilter(TaxonomicFilterGroupType.Events, null, { name: 'All events' })
        expect(logic.values.recentFilters).toHaveLength(0)
    })
})
