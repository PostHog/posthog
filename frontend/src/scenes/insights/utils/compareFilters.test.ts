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
})
