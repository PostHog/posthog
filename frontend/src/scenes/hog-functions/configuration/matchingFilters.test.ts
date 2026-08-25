import { FilterLogicalOperator, PropertyFilterType } from '~/types'

import { buildEventMatchingFilters } from './matchingFilters'

describe('buildEventMatchingFilters', () => {
    it('ORs event and action filters together, ANDing each with its own properties and the global ones', () => {
        const result = buildEventMatchingFilters({
            events: [{ id: '$pageview', type: 'events', properties: [] }],
            actions: [{ id: '1', type: 'actions', properties: [] }],
            properties: [{ type: PropertyFilterType.Person, key: 'plan', operator: 'exact', value: 'paid' }],
        })

        expect(result.type).toEqual(FilterLogicalOperator.And)
        const [seriesGroup, globalGroup] = result.values
        expect(seriesGroup.type).toEqual(FilterLogicalOperator.Or)
        expect(seriesGroup.values).toHaveLength(2)
        expect(seriesGroup.values[0]).toEqual({
            type: FilterLogicalOperator.And,
            values: [{ type: PropertyFilterType.HogQL, key: "event = '$pageview'" }],
        })
        expect(seriesGroup.values[1]).toEqual({
            type: FilterLogicalOperator.And,
            values: [{ type: PropertyFilterType.HogQL, key: 'matchesAction(1)' }],
        })
        expect(globalGroup).toEqual({
            type: FilterLogicalOperator.And,
            values: [{ type: PropertyFilterType.Person, key: 'plan', operator: 'exact', value: 'paid' }],
        })
    })

    it('does not mutate the events/actions arrays passed in', () => {
        const events = [{ id: '$pageview', type: 'events' as const, properties: [] }]
        const actions = [{ id: '1', type: 'actions' as const, properties: [] }]

        buildEventMatchingFilters({ events, actions })

        expect(events).toHaveLength(1)
        expect(actions).toHaveLength(1)
    })
})
