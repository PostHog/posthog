import { initKeaTests } from '~/test/init'
import { PersonPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

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
        logic = recentTaxonomicFiltersLogic.build()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('starts with an empty list', () => {
        expect(logic.values.recentFilters).toEqual([])
    })

    it('records a selection with groupType, groupName, value, item, and timestamp', () => {
        const item = { name: '$pageview', id: 'uuid-1' }
        logic.actions.recordRecentFilter({
            groupType: TaxonomicFilterGroupType.Events,
            groupName: 'Events',
            value: '$pageview',
            item: item,
        })

        const filters = logic.values.recentFilters
        expect(filters).toHaveLength(1)
        expect(filters[0]).toEqual(
            expect.objectContaining({
                groupType: TaxonomicFilterGroupType.Events,
                groupName: 'Events',
                value: '$pageview',
                item,
            })
        )
        expect(typeof filters[0].timestamp).toBe('number')
    })

    it('prepends new entries so most recent is first', () => {
        logic.actions.recordRecentFilter({
            groupType: TaxonomicFilterGroupType.Events,
            groupName: 'Events',
            value: 'first',
            item: { name: 'first' },
        })
        logic.actions.recordRecentFilter({
            groupType: TaxonomicFilterGroupType.Events,
            groupName: 'Events',
            value: 'second',
            item: { name: 'second' },
        })

        expect(logic.values.recentFilters[0].value).toBe('second')
        expect(logic.values.recentFilters[1].value).toBe('first')
    })

    it('deduplicates by groupType + value, keeping the most recent', () => {
        logic.actions.recordRecentFilter({
            groupType: TaxonomicFilterGroupType.Events,
            groupName: 'Events',
            value: '$pageview',
            item: {
                name: '$pageview',
            },
        })
        logic.actions.recordRecentFilter({
            groupType: TaxonomicFilterGroupType.Events,
            groupName: 'Events',
            value: '$click',
            item: { name: '$click' },
        })
        logic.actions.recordRecentFilter({
            groupType: TaxonomicFilterGroupType.Events,
            groupName: 'Events',
            value: '$pageview',
            item: {
                name: '$pageview',
                updated: true,
            },
        })

        const filters = logic.values.recentFilters
        expect(filters).toHaveLength(2)
        expect(filters[0].value).toBe('$pageview')
        expect(filters[0].item).toEqual({ name: '$pageview', updated: true })
        expect(filters[1].value).toBe('$click')
    })

    it('keeps property filters with the same key but different values as separate recents', () => {
        logic.actions.recordRecentFilter({
            groupType: TaxonomicFilterGroupType.EventProperties,
            groupName: 'Event properties',
            value: '$browser',
            item: { name: '$browser' },
            propertyFilter: {
                type: PropertyFilterType.Event,
                key: '$browser',
                operator: PropertyOperator.Exact,
                value: 'Chrome',
            },
        })
        logic.actions.recordRecentFilter({
            groupType: TaxonomicFilterGroupType.EventProperties,
            groupName: 'Event properties',
            value: '$browser',
            item: { name: '$browser' },
            propertyFilter: {
                type: PropertyFilterType.Event,
                key: '$browser',
                operator: PropertyOperator.Exact,
                value: 'Safari',
            },
        })

        const filters = logic.values.recentFilters
        expect(filters).toHaveLength(2)
        expect((filters[0].propertyFilter as any).value).toBe('Safari')
        expect((filters[1].propertyFilter as any).value).toBe('Chrome')
    })

    it('deduplicates property filters with the same key, operator, and value', () => {
        logic.actions.recordRecentFilter({
            groupType: TaxonomicFilterGroupType.EventProperties,
            groupName: 'Event properties',
            value: '$browser',
            item: { name: '$browser' },
            propertyFilter: {
                type: PropertyFilterType.Event,
                key: '$browser',
                operator: PropertyOperator.Exact,
                value: 'Chrome',
            },
        })
        logic.actions.recordRecentFilter({
            groupType: TaxonomicFilterGroupType.EventProperties,
            groupName: 'Event properties',
            value: '$browser',
            item: { name: '$browser' },
            propertyFilter: {
                type: PropertyFilterType.Event,
                key: '$browser',
                operator: PropertyOperator.Exact,
                value: 'Chrome',
            },
        })

        expect(logic.values.recentFilters).toHaveLength(1)
    })

    it('does not replace a complete property filter with a key-only record', () => {
        const complete = {
            type: PropertyFilterType.Person,
            key: 'email',
            operator: PropertyOperator.Exact,
            value: 'alice@example.com',
        } satisfies PersonPropertyFilter
        logic.actions.recordRecentFilter({
            groupType: TaxonomicFilterGroupType.PersonProperties,
            groupName: 'Person properties',
            value: 'email',
            item: { name: 'email' },
            propertyFilter: complete,
        })
        logic.actions.recordRecentFilter({
            groupType: TaxonomicFilterGroupType.PersonProperties,
            groupName: 'Person properties',
            value: 'email',
            item: {
                name: 'email',
            },
        })

        const filters = logic.values.recentFilters
        expect(filters).toHaveLength(1)
        expect(filters[0].propertyFilter).toMatchObject(complete)
    })

    it('replaces a key-only entry when recording a complete filter for the same key', () => {
        logic.actions.recordRecentFilter({
            groupType: TaxonomicFilterGroupType.PersonProperties,
            groupName: 'Person properties',
            value: 'email',
            item: {
                name: 'email',
            },
        })
        const complete = {
            type: PropertyFilterType.Person,
            key: 'email',
            operator: PropertyOperator.Exact,
            value: 'bob@example.com',
        } satisfies PersonPropertyFilter
        logic.actions.recordRecentFilter({
            groupType: TaxonomicFilterGroupType.PersonProperties,
            groupName: 'Person properties',
            value: 'email',
            item: { name: 'email' },
            propertyFilter: complete,
        })

        const filters = logic.values.recentFilters
        expect(filters).toHaveLength(1)
        expect(filters[0].propertyFilter).toMatchObject(complete)
    })

    it('allows the same value in different group types', () => {
        logic.actions.recordRecentFilter({
            groupType: TaxonomicFilterGroupType.Events,
            groupName: 'Events',
            value: 'name',
            item: { name: 'name' },
        })
        logic.actions.recordRecentFilter({
            groupType: TaxonomicFilterGroupType.PersonProperties,
            groupName: 'Person properties',
            value: 'name',
            item: {
                name: 'name',
            },
        })

        expect(logic.values.recentFilters).toHaveLength(2)
    })

    it(`caps entries at ${MAX_RECENT_FILTERS}`, () => {
        for (let i = 0; i < MAX_RECENT_FILTERS + 5; i++) {
            logic.actions.recordRecentFilter({
                groupType: TaxonomicFilterGroupType.Events,
                groupName: 'Events',
                value: `event-${i}`,
                item: {
                    name: `event-${i}`,
                },
            })
        }

        expect(logic.values.recentFilters).toHaveLength(MAX_RECENT_FILTERS)
        expect(logic.values.recentFilters[0].value).toBe(`event-${MAX_RECENT_FILTERS + 4}`)
    })

    it('drops entries older than 30 days on next write', () => {
        jest.useFakeTimers()
        try {
            logic.actions.recordRecentFilter({
                groupType: TaxonomicFilterGroupType.Events,
                groupName: 'Events',
                value: 'old-event',
                item: {
                    name: 'old-event',
                },
            })
            expect(logic.values.recentFilters).toHaveLength(1)

            jest.advanceTimersByTime(RECENT_FILTER_MAX_AGE_MS + 1000)

            logic.actions.recordRecentFilter({
                groupType: TaxonomicFilterGroupType.Events,
                groupName: 'Events',
                value: 'new-event',
                item: {
                    name: 'new-event',
                },
            })

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
        {
            groupType: TaxonomicFilterGroupType.MaxAIContext,
            description: 'MaxAIContext',
        },
        {
            groupType: TaxonomicFilterGroupType.DataWarehouse,
            description: 'DataWarehouse',
        },
        {
            groupType: TaxonomicFilterGroupType.DataWarehouseProperties,
            description: 'DataWarehouseProperties',
        },
        {
            groupType: TaxonomicFilterGroupType.DataWarehousePersonProperties,
            description: 'DataWarehousePersonProperties',
        },
    ])('ignores selections from excluded group type: $description', ({ groupType }) => {
        logic.actions.recordRecentFilter({
            groupType: groupType,
            groupName: 'Ignored',
            value: 'some-value',
            item: { name: 'some-value' },
        })
        expect(logic.values.recentFilters).toHaveLength(0)
    })

    it('ignores selections with null value', () => {
        logic.actions.recordRecentFilter({
            groupType: TaxonomicFilterGroupType.Events,
            groupName: 'Events',
            value: null,
            item: { name: 'All events' },
        })
        expect(logic.values.recentFilters).toHaveLength(0)
    })

    it('stores a property filter when provided', () => {
        const propertyFilter = { key: '$browser', type: 'event', operator: 'exact', value: 'Chrome' }
        logic.actions.recordRecentFilter({
            groupType: TaxonomicFilterGroupType.EventProperties,
            groupName: 'Event properties',
            value: '$browser',
            item: { name: '$browser' },
            propertyFilter: propertyFilter as any,
        })

        expect(logic.values.recentFilters[0].propertyFilter).toEqual(propertyFilter)
    })

    it('stores teamId when provided', () => {
        logic.actions.recordRecentFilter({
            groupType: TaxonomicFilterGroupType.Events,
            groupName: 'Events',
            value: '$pageview',
            item: {
                name: '$pageview',
            },
            teamId: 42,
        })

        expect(logic.values.recentFilters[0].teamId).toBe(42)
    })

    it('stores groupName for display purposes', () => {
        logic.actions.recordRecentFilter({
            groupType: TaxonomicFilterGroupType.EventProperties,
            groupName: 'Event properties',
            value: '$browser',
            item: {
                name: '$browser',
            },
        })

        expect(logic.values.recentFilters[0].groupName).toBe('Event properties')
    })

    it('omits teamId from stored entry when not provided', () => {
        logic.actions.recordRecentFilter({
            groupType: TaxonomicFilterGroupType.Events,
            groupName: 'Events',
            value: '$pageview',
            item: {
                name: '$pageview',
            },
        })

        expect(logic.values.recentFilters[0].teamId).toBeUndefined()
    })

    describe('selectingKeyOnly recordings', () => {
        const complete = {
            type: PropertyFilterType.Person,
            key: 'email',
            operator: PropertyOperator.Exact,
            value: 'alice@example.com',
        } satisfies PersonPropertyFilter

        it('selectingKeyOnly write coexists with an existing complete record for the same key', () => {
            logic.actions.recordRecentFilter({
                groupType: TaxonomicFilterGroupType.PersonProperties,
                groupName: 'Person properties',
                value: 'email',
                item: { name: 'email' },
                propertyFilter: complete,
            })
            logic.actions.recordRecentFilter({
                groupType: TaxonomicFilterGroupType.PersonProperties,
                groupName: 'Person properties',
                value: 'email',
                item: { name: 'email' },
                selectingKeyOnly: true,
            })

            const filters = logic.values.recentFilters
            expect(filters).toHaveLength(2)
            expect(filters[0].propertyFilter).toBeUndefined()
            expect(filters[1].propertyFilter).toMatchObject(complete)
        })

        it('non-selectingKeyOnly partial write is still suppressed when a complete record exists', () => {
            logic.actions.recordRecentFilter({
                groupType: TaxonomicFilterGroupType.PersonProperties,
                groupName: 'Person properties',
                value: 'email',
                item: { name: 'email' },
                propertyFilter: complete,
            })
            logic.actions.recordRecentFilter({
                groupType: TaxonomicFilterGroupType.PersonProperties,
                groupName: 'Person properties',
                value: 'email',
                item: {
                    name: 'email',
                },
            })

            expect(logic.values.recentFilters).toHaveLength(1)
            expect(logic.values.recentFilters[0].propertyFilter).toMatchObject(complete)
        })

        it('selectingKeyOnly writes for the same key dedup to the most recent', () => {
            logic.actions.recordRecentFilter({
                groupType: TaxonomicFilterGroupType.EventProperties,
                groupName: 'Event properties',
                value: '$browser',
                item: { name: '$browser' },
                selectingKeyOnly: true,
            })
            logic.actions.recordRecentFilter({
                groupType: TaxonomicFilterGroupType.EventProperties,
                groupName: 'Event properties',
                value: '$browser',
                item: { name: '$browser', refreshed: true },
                selectingKeyOnly: true,
            })

            const filters = logic.values.recentFilters
            expect(filters).toHaveLength(1)
            expect(filters[0].item).toEqual({ name: '$browser', refreshed: true })
        })

        it('a selectingKeyOnly write replaces an existing complete record that has expired', () => {
            jest.useFakeTimers()
            try {
                logic.actions.recordRecentFilter({
                    groupType: TaxonomicFilterGroupType.PersonProperties,
                    groupName: 'Person properties',
                    value: 'email',
                    item: { name: 'email' },
                    propertyFilter: complete,
                })

                jest.advanceTimersByTime(RECENT_FILTER_MAX_AGE_MS + 1000)

                logic.actions.recordRecentFilter({
                    groupType: TaxonomicFilterGroupType.PersonProperties,
                    groupName: 'Person properties',
                    value: 'email',
                    item: { name: 'email' },
                    selectingKeyOnly: true,
                })

                const filters = logic.values.recentFilters
                expect(filters).toHaveLength(1)
                expect(filters[0].propertyFilter).toBeUndefined()
            } finally {
                jest.useRealTimers()
            }
        })

        it('keeps both key-only and complete entries within the MAX_RECENT_FILTERS cap', () => {
            for (let i = 0; i < MAX_RECENT_FILTERS - 1; i++) {
                logic.actions.recordRecentFilter({
                    groupType: TaxonomicFilterGroupType.Events,
                    groupName: 'Events',
                    value: `event-${i}`,
                    item: {
                        name: `event-${i}`,
                    },
                })
            }
            logic.actions.recordRecentFilter({
                groupType: TaxonomicFilterGroupType.PersonProperties,
                groupName: 'Person properties',
                value: 'email',
                item: { name: 'email' },
                propertyFilter: complete,
            })
            logic.actions.recordRecentFilter({
                groupType: TaxonomicFilterGroupType.PersonProperties,
                groupName: 'Person properties',
                value: 'email',
                item: { name: 'email' },
                selectingKeyOnly: true,
            })

            const filters = logic.values.recentFilters
            expect(filters).toHaveLength(MAX_RECENT_FILTERS)
            const emailRecords = filters.filter(
                (f) => f.groupType === TaxonomicFilterGroupType.PersonProperties && f.value === 'email'
            )
            expect(emailRecords).toHaveLength(2)
            expect(emailRecords[0].propertyFilter).toBeUndefined()
            expect(emailRecords[1].propertyFilter).toMatchObject(complete)
            // Oldest event was evicted to make room for the selectingKeyOnly entry that followed the complete one.
            expect(filters.find((f) => f.value === 'event-0')).toBeUndefined()
        })
    })
})
