import { FilterLogicalOperator, PropertyFilterType, PropertyOperator } from '~/types'

import { buildEventMatchingFilters } from './matchingFilters'

describe('buildEventMatchingFilters', () => {
    it('ORs event and action filters together, ANDing each with its own properties and the global ones', () => {
        const result = buildEventMatchingFilters({
            events: [{ id: '$pageview', type: 'events', properties: [] }],
            actions: [{ id: '1', type: 'actions', properties: [] }],
            properties: [
                { type: PropertyFilterType.Person, key: 'plan', operator: PropertyOperator.Exact, value: 'paid' },
            ],
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
            values: [{ type: PropertyFilterType.Person, key: 'plan', operator: PropertyOperator.Exact, value: 'paid' }],
        })
    })

    it('falls back to an always-true filter for an all-events series and omits an empty global group', () => {
        // The taxonomic filter stores "All events" as id: null, so the stored data is looser
        // than CyclotronJobFilterBase. Without the `true` fallback the series contributes an
        // empty AND group and the matching-events preview breaks for all-events functions.
        const result = buildEventMatchingFilters({
            events: [{ id: null as unknown as string, type: 'events', properties: [] }],
        })

        expect(result.values).toHaveLength(1)
        const [seriesGroup] = result.values
        expect(seriesGroup.values).toEqual([
            {
                type: FilterLogicalOperator.And,
                values: [{ type: PropertyFilterType.HogQL, key: 'true' }],
            },
        ])
    })

    it("keeps each series' own properties ANDed with its id filter", () => {
        const eventProperty = {
            type: PropertyFilterType.Event,
            key: 'channel',
            operator: PropertyOperator.Exact,
            value: 'C1',
        }
        const actionProperty = {
            type: PropertyFilterType.Event,
            key: 'plan',
            operator: PropertyOperator.Exact,
            value: 'paid',
        }
        const result = buildEventMatchingFilters({
            events: [{ id: '$pageview', type: 'events', properties: [eventProperty] }],
            actions: [{ id: '1', type: 'actions', properties: [actionProperty] }],
        })

        const [seriesGroup] = result.values
        expect(seriesGroup.values).toEqual([
            {
                type: FilterLogicalOperator.And,
                values: [eventProperty, { type: PropertyFilterType.HogQL, key: "event = '$pageview'" }],
            },
            {
                type: FilterLogicalOperator.And,
                values: [actionProperty, { type: PropertyFilterType.HogQL, key: 'matchesAction(1)' }],
            },
        ])
    })

    it('does not mutate the events/actions arrays passed in', () => {
        const events = [{ id: '$pageview', type: 'events' as const, properties: [] }]
        const actions = [{ id: '1', type: 'actions' as const, properties: [] }]

        buildEventMatchingFilters({ events, actions })

        expect(events).toHaveLength(1)
        expect(actions).toHaveLength(1)
    })
})
