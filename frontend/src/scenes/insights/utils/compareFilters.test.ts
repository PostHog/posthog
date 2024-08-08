import { AnyFilterType, BaseMathType, Entity, EntityTypes, InsightType, PropertyGroupFilter } from '~/types'

import { cleanFilter, compareFilters } from './compareFilters'

describe('clean', () => {
    it('runs cleanFilters on the input', () => {
        const filters: Partial<AnyFilterType> = {}

        const result = cleanFilter(filters, false)

        expect(result.insight).toEqual('TRENDS')
        expect(filters.insight).toBeUndefined() // doesn't mutate original
    })

    it('removes keys with "empty" values', () => {
        const filters: Partial<AnyFilterType> = {
            filter_test_accounts: undefined,
            events: [],
            properties: {} as PropertyGroupFilter,
        }

        const result = cleanFilter(filters, false)

        // undefined values
        expect(result.hasOwnProperty('filter_test_accounts')).toEqual(false)
        expect(filters.hasOwnProperty('filter_test_accounts')).toEqual(true) // doesn't mutate original

        // empty arrays
        expect(result.hasOwnProperty('events')).toEqual(false)
        expect(filters.hasOwnProperty('events')).toEqual(true) // doesn't mutate original

        // empty objects
        expect(result.hasOwnProperty('properties')).toEqual(false)
        expect(filters.hasOwnProperty('properties')).toEqual(true) // doesn't mutate original
    })

    it('removes unnecessary order from events', () => {
        const filters: Partial<AnyFilterType> = { events: [{ type: 'events', order: 0 }] }

        const result = cleanFilter(filters, false)

        expect(result.events?.[0].order).toBeUndefined()
        expect(filters.events?.[0].order).toEqual(0) // doesn't mutate original
    })

    it('removes unnecessary default math type from events', () => {
        const filters: Partial<AnyFilterType> = { events: [{ type: 'events', math: BaseMathType.TotalCount }] }

        const result = cleanFilter(filters, false)

        expect(result.events?.[0].math).toBeUndefined()
        expect(filters.events?.[0].math).toEqual('total') // doesn't mutate original
    })

    it('removes unnecessary order from actions', () => {
        const filters: Partial<AnyFilterType> = { actions: [{ type: 'actions', order: 0 }] as Entity[] }

        const result = cleanFilter(filters, false)

        expect(result.actions?.[0].order).toBeUndefined()
        expect(filters.actions?.[0].order).toEqual(0) // doesn't mutate original
    })

    it('removes entity_type for persons modal from result', () => {
        const filters: Partial<AnyFilterType> = { entity_type: EntityTypes.EVENTS }

        const result = cleanFilter(filters, false)

        expect(result.entity_type).toBeUndefined()
        expect(filters.entity_type).toEqual(EntityTypes.EVENTS) // doesn't mutate original
    })
})

describe('compareFilters', () => {
    it('returns true for semantically equal filters', () => {
        const a: Partial<AnyFilterType> = {
            events: [{ order: 0, math: BaseMathType.TotalCount, name: '$pageview' }],
            entity_type: EntityTypes.EVENTS,
        }
        const b: Partial<AnyFilterType> = { insight: InsightType.TRENDS, events: [{ name: '$pageview' }] }

        const result = compareFilters(a, b, false)

        expect(result).toEqual(true)
    })

    it('returns false for semantically un-equal filters', () => {
        const a: Partial<AnyFilterType> = { insight: InsightType.TRENDS }
        const b: Partial<AnyFilterType> = { insight: InsightType.FUNNELS }

        const result = compareFilters(a, b, false)

        expect(result).toEqual(false)
    })

    it('handles test account filters', () => {
        const a: Partial<AnyFilterType> = { insight: InsightType.TRENDS, filter_test_accounts: true }
        const b: Partial<AnyFilterType> = { insight: InsightType.TRENDS }

        const result1 = compareFilters(a, b, true)
        const result2 = compareFilters(a, b, false)

        expect(result1).toEqual(true)
        expect(result2).toEqual(false)
    })

    it('handles breakdown filters', () => {
        const a: Partial<AnyFilterType> = {
            insight: InsightType.TRENDS,
            breakdown: '$browser',
            breakdown_type: 'event',
        }
        const b: Partial<AnyFilterType> = {
            insight: InsightType.TRENDS,
            breakdown: '$test',
            breakdown_type: 'event',
        }

        expect(compareFilters(a, b, false)).toEqual(false)
    })

    it('handles a breakdown filter with different types', () => {
        const a: Partial<AnyFilterType> = {
            insight: InsightType.TRENDS,
            breakdown: '$browser',
            breakdown_type: 'event',
        }
        const b: Partial<AnyFilterType> = {
            insight: InsightType.TRENDS,
            breakdowns: [
                {
                    property: '$browser',
                    type: 'event',
                },
            ],
        }

        expect(compareFilters(a, b, false)).toEqual(false)
    })

    it('handles multiple breakdowns', () => {
        const a: Partial<AnyFilterType> = {
            insight: InsightType.TRENDS,
            breakdowns: [
                {
                    property: '$browser',
                    type: 'event',
                },
                {
                    property: '$prop',
                    type: 'event',
                },
            ],
        }
        const b: Partial<AnyFilterType> = {
            insight: InsightType.TRENDS,
            breakdowns: [
                {
                    property: '$browser',
                    type: 'event',
                },
            ],
        }

        expect(compareFilters(a, b, false)).toEqual(false)
    })

    it('handles equal multiple breakdowns', () => {
        const a: Partial<AnyFilterType> = {
            insight: InsightType.TRENDS,
            breakdowns: [
                {
                    property: '$browser',
                    type: 'event',
                },
                {
                    property: '$prop',
                    type: 'event',
                },
            ],
        }
        const b: Partial<AnyFilterType> = {
            insight: InsightType.TRENDS,
            breakdowns: [
                {
                    property: '$browser',
                    type: 'event',
                },
                {
                    property: '$prop',
                    type: 'event',
                },
            ],
        }

        expect(compareFilters(a, b, false)).toEqual(true)
    })

    it('handles multiple breakdowns with properties', () => {
        const a: Partial<AnyFilterType> = {
            insight: InsightType.TRENDS,
            breakdowns: [
                {
                    property: '$browser',
                    type: 'group',
                    group_type_index: 1,
                    histogram_bin_count: 10,
                },
                {
                    property: '$pathname',
                    type: 'group',
                    normalize_url: true,
                },
            ],
        }
        let b: Partial<AnyFilterType> = {
            insight: InsightType.TRENDS,
            breakdowns: [
                {
                    property: '$browser',
                    type: 'group',
                    group_type_index: 1,
                    histogram_bin_count: 10,
                },
                {
                    property: '$pathname',
                    type: 'group',
                    normalize_url: false,
                },
            ],
        }

        expect(compareFilters(a, b, false)).toEqual(false)

        b = {
            insight: InsightType.TRENDS,
            breakdowns: [
                {
                    property: '$browser',
                    type: 'group',
                    group_type_index: 0,
                    histogram_bin_count: 10,
                },
                {
                    property: '$pathname',
                    type: 'group',
                    normalize_url: true,
                },
            ],
        }

        expect(compareFilters(a, b, false)).toEqual(false)
    })
})
