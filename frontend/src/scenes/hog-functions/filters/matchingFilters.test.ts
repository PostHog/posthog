import { FilterLogicalOperator, PropertyFilterType, PropertyOperator } from '~/types'

import { matchingFiltersToPropertyGroup } from './matchingFilters'

describe('matchingFiltersToPropertyGroup', () => {
    it('pins each event to its own OR branch', () => {
        const group = matchingFiltersToPropertyGroup({
            events: [
                { id: '$pageview', type: 'events' },
                { id: 'purchase', type: 'events' },
            ],
        })

        expect(group).toEqual({
            type: FilterLogicalOperator.And,
            values: [
                {
                    type: FilterLogicalOperator.Or,
                    values: [
                        {
                            type: FilterLogicalOperator.And,
                            values: [{ type: PropertyFilterType.HogQL, key: "event = '$pageview'" }],
                        },
                        {
                            type: FilterLogicalOperator.And,
                            values: [{ type: PropertyFilterType.HogQL, key: "event = 'purchase'" }],
                        },
                    ],
                },
            ],
        })
    })

    it('keeps an event with no id from narrowing the count', () => {
        const group = matchingFiltersToPropertyGroup({ events: [{ id: '', type: 'events' }] })

        expect(group.values[0].values).toEqual([
            { type: FilterLogicalOperator.And, values: [{ type: PropertyFilterType.HogQL, key: 'true' }] },
        ])
    })

    it('ANDs the global properties over every branch', () => {
        const group = matchingFiltersToPropertyGroup({
            events: [{ id: '$pageview', type: 'events' }],
            actions: [{ id: '42', type: 'actions' }],
            properties: [
                {
                    key: 'email',
                    value: 'a@example.com',
                    operator: PropertyOperator.Exact,
                    type: PropertyFilterType.Person,
                },
            ],
        })

        expect(group.values).toHaveLength(2)
        expect(group.values[0].values).toEqual([
            {
                type: FilterLogicalOperator.And,
                values: [{ type: PropertyFilterType.HogQL, key: "event = '$pageview'" }],
            },
            { type: FilterLogicalOperator.And, values: [{ type: PropertyFilterType.HogQL, key: 'matchesAction(42)' }] },
        ])
        expect(group.values[1]).toEqual({
            type: FilterLogicalOperator.And,
            values: [
                {
                    key: 'email',
                    value: 'a@example.com',
                    operator: PropertyOperator.Exact,
                    type: PropertyFilterType.Person,
                },
            ],
        })
    })
})
