import { NodeKind } from '~/queries/schema/schema-general'
import {
    BaseMathType,
    CalendarHeatmapMathType,
    FilterLogicalOperator,
    FunnelMathType,
    PropertyFilterType,
    PropertyMathType,
    PropertyOperator,
} from '~/types'

import { MathAvailability } from './ActionFilterRow/types'
import { cleanSeriesNodes } from './cleanSeriesNodes'
import { SeriesNode } from './seriesNode'

const pageview = { kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' }

describe('cleanSeriesNodes', () => {
    it.each([
        {
            name: 'keeps math fields the picker does not edit',
            mathAvailability: MathAvailability.All,
            series: [
                {
                    ...pageview,
                    math: PropertyMathType.Sum,
                    math_property: 'revenue',
                    math_property_revenue_currency: { static: 'EUR' },
                    math_multiplier: 0.01,
                },
            ],
            expected: [
                {
                    ...pageview,
                    math: PropertyMathType.Sum,
                    math_property: 'revenue',
                    math_property_revenue_currency: { static: 'EUR' },
                    math_multiplier: 0.01,
                },
            ],
        },
        {
            name: 'keeps an actors math in stickiness',
            mathAvailability: MathAvailability.ActorsOnly,
            series: [{ ...pageview, math: 'unique_group', math_group_type_index: 1 }],
            expected: [{ ...pageview, math: 'unique_group', math_group_type_index: 1 }],
        },
        {
            name: 'drops math a funnel step cannot use',
            mathAvailability: MathAvailability.FunnelsOnly,
            series: [
                { ...pageview, math: BaseMathType.UniqueUsers },
                { ...pageview, math: FunnelMathType.FirstTimeForUser, math_property: '$browser' },
            ],
            expected: [pageview, { ...pageview, math: FunnelMathType.FirstTimeForUser }],
        },
        {
            name: 'drops math a calendar heatmap cannot use',
            mathAvailability: MathAvailability.CalendarHeatmapOnly,
            series: [
                { ...pageview, math: BaseMathType.WeeklyActiveUsers },
                { ...pageview, math: CalendarHeatmapMathType.UniqueUsers },
            ],
            expected: [pageview, { ...pageview, math: CalendarHeatmapMathType.UniqueUsers }],
        },
        {
            name: 'drops all math and keeps the exclusion step range',
            mathAvailability: MathAvailability.None,
            series: [{ ...pageview, math: BaseMathType.TotalCount, funnelFromStep: 0, funnelToStep: 2 }],
            expected: [{ ...pageview, funnelFromStep: 0, funnelToStep: 2 }],
        },
        {
            name: 'drops unset and empty fields',
            mathAvailability: MathAvailability.All,
            series: [
                {
                    ...pageview,
                    custom_name: '',
                    properties: [],
                    math: BaseMathType.TotalCount,
                    math_property: undefined,
                    math_hogql: undefined,
                },
            ],
            expected: [{ ...pageview, math: BaseMathType.TotalCount }],
        },
        {
            name: 'cleans the nodes inside a group',
            mathAvailability: MathAvailability.All,
            series: [
                {
                    kind: NodeKind.GroupNode,
                    operator: FilterLogicalOperator.Or,
                    name: '$pageview',
                    nodes: [
                        {
                            ...pageview,
                            properties: [{ key: '$browser', value: 'Chrome', type: PropertyFilterType.Event }],
                        },
                    ],
                },
            ],
            expected: [
                {
                    kind: NodeKind.GroupNode,
                    operator: FilterLogicalOperator.Or,
                    name: '$pageview',
                    math: BaseMathType.TotalCount,
                    nodes: [
                        {
                            ...pageview,
                            math: BaseMathType.TotalCount,
                            properties: [
                                {
                                    key: '$browser',
                                    value: 'Chrome',
                                    operator: PropertyOperator.Exact,
                                    type: PropertyFilterType.Event,
                                },
                            ],
                        },
                    ],
                },
            ],
        },
    ])('$name', ({ mathAvailability, series, expected }) => {
        expect(cleanSeriesNodes(series as SeriesNode[], mathAvailability)).toStrictEqual(expected)
    })
})
