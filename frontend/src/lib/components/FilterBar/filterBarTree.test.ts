import { AnyPropertyFilter, EntityTypes, FilterLogicalOperator, PropertyFilterType, PropertyOperator } from '~/types'

import { filterBarSummary } from './filterBarSummary'
import { contradictsEarlierSibling, pruneGroups, treeFromValue, valueFromNodes } from './filterBarTree'

const And = FilterLogicalOperator.And
const Or = FilterLogicalOperator.Or

const safari: AnyPropertyFilter = {
    type: PropertyFilterType.Event,
    key: '$browser',
    operator: PropertyOperator.Exact,
    value: ['Safari'],
}
const france: AnyPropertyFilter = {
    type: PropertyFilterType.Event,
    key: '$geoip_country_code',
    operator: PropertyOperator.Exact,
    value: ['FR'],
}
const recording = {
    type: PropertyFilterType.Recording,
    key: 'active_seconds',
    operator: PropertyOperator.GreaterThan,
    value: null,
} as AnyPropertyFilter

describe('filterBarTree', () => {
    it.each([
        ['a flat list', [safari, france], { type: And, values: [{ type: And, values: [safari, france] }] }],
        [
            'an OR at the top, which stays OR under the AND the bar joins with',
            {
                type: Or,
                values: [
                    { type: And, values: [safari] },
                    { type: And, values: [france] },
                ],
            },
            { type: And, values: [{ type: Or, values: [safari, france] }] },
        ],
        [
            'two AND branches under an OR',
            {
                type: Or,
                values: [
                    { type: And, values: [safari, france] },
                    { type: And, values: [france, safari] },
                ],
            },
            {
                type: And,
                values: [
                    {
                        type: Or,
                        values: [
                            { type: And, values: [safari, france] },
                            { type: And, values: [france, safari] },
                        ],
                    },
                ],
            },
        ],
        [
            'an event with properties and a negation',
            {
                type: And,
                values: [
                    {
                        type: And,
                        values: [
                            { type: EntityTypes.EVENTS, id: '$pageview', name: '$pageview', properties: [safari] },
                            { type: EntityTypes.EVENTS, id: '$exception', name: '$exception', negation: true },
                        ],
                    },
                ],
            },
            {
                type: And,
                values: [
                    {
                        type: And,
                        values: [
                            { type: EntityTypes.EVENTS, id: '$pageview', name: '$pageview', properties: [safari] },
                            { type: EntityTypes.EVENTS, id: '$exception', name: '$exception', negation: true },
                        ],
                    },
                ],
            },
        ],
        [
            'a filter type the bar has no category for, even without a value',
            [recording],
            { type: And, values: [{ type: And, values: [recording] }] },
        ],
    ])('keeps the meaning of %s', (_, value, expected) => {
        expect(valueFromNodes(treeFromValue(value as any).nodes)).toEqual(expected)
    })

    it.each([
        ['is values under an OR', Or, PropertyOperator.Exact, true],
        ['is not values under an AND', And, PropertyOperator.IsNot, true],
        ['is values under an AND, which contradict', And, PropertyOperator.Exact, false],
        ['is not values under an OR, which match everything', Or, PropertyOperator.IsNot, false],
    ])('merges only rows whose meaning survives: %s', (_, type, operator, merges) => {
        const row = (value: string): AnyPropertyFilter => ({ ...safari, operator, value: [value] }) as AnyPropertyFilter
        const value = { type: And, values: [{ type, values: [row('A'), row('B')] }] }
        const { nodes } = treeFromValue(value as any)
        expect(nodes.length === 1 && 'filter' in nodes[0] ? (nodes[0].filter as any).value : null).toEqual(
            merges ? ['A', 'B'] : null
        )
    })

    it('flags an AND row that contradicts an earlier row, but not one that can still match', () => {
        const row = (value: string): AnyPropertyFilter => ({ ...safari, value: [value] }) as AnyPropertyFilter
        const rows = [
            { id: 1, filter: row('A') },
            { id: 2, filter: row('B') },
            { id: 3, filter: { ...safari, value: ['A', 'B'] } as AnyPropertyFilter },
        ]
        expect(rows.map((_, index) => contradictsEarlierSibling(rows, index, And))).toEqual([false, true, false])
        expect(contradictsEarlierSibling(rows, 1, Or)).toBe(false)
    })

    it('reads the nesting as one sentence', () => {
        const { nodes } = treeFromValue({
            type: And,
            values: [
                { type: And, values: [safari] },
                {
                    type: Or,
                    values: [france, { ...france, key: '$os', value: ['iOS'] } as AnyPropertyFilter],
                },
                {
                    type: And,
                    values: [{ type: EntityTypes.EVENTS, id: 'signed_up', name: 'signed_up', negation: true }],
                },
            ],
        } as any)
        expect(filterBarSummary(nodes)).toBe(
            'Browser is Safari and (Country code is FR or OS is iOS) and did not perform signed_up'
        )
    })

    it('leaves a chip without a value out of the value, and unwraps a group that has one row left', () => {
        const pending = { ...safari, value: null } as AnyPropertyFilter
        const { nodes } = treeFromValue({ type: Or, values: [france, pending] } as any)
        expect(valueFromNodes(nodes)).toEqual({ type: And, values: [{ type: And, values: [france] }] })
        const lone = treeFromValue([france]).nodes
        expect(pruneGroups([{ id: 99, type: Or, children: lone }])).toEqual(lone)
    })
})
