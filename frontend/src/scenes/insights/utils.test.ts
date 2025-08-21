import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import {
    compareInsightTopLevelSections,
    extractObjectDiffKeys,
    formatAggregationValue,
    formatBreakdownLabel,
    formatBreakdownType,
    getDisplayNameFromEntityFilter,
    getDisplayNameFromEntityNode,
    getTrendDatasetKey,
} from 'scenes/insights/utils'
import { IndexedTrendResult } from 'scenes/trends/types'

import { ActionsNode, BreakdownFilter, EventsNode, InsightQueryNode, NodeKind } from '~/queries/schema/schema-general'
import { isEventsNode } from '~/queries/utils'
import { CompareLabelType, Entity, EntityFilter, FilterType, InsightType } from '~/types'

const createFilter = (id?: Entity['id'], name?: string, custom_name?: string): EntityFilter => {
    return {
        custom_name,
        name: name ?? null,
        id: id ?? null,
    }
}

describe('getDisplayNameFromEntityFilter()', () => {
    const paramsToExpected: [EntityFilter, boolean, string | null][] = [
        [createFilter(3, 'name', 'custom_name'), true, 'custom_name'],
        [createFilter(3, 'name', ''), true, 'name'],
        [createFilter(3, 'name', '    '), true, 'name'],
        [createFilter(3, 'name'), true, 'name'],
        [createFilter(3, '', ''), true, '3'],
        [createFilter(3, '  ', '    '), true, '3'],
        [createFilter(3), true, '3'],
        [createFilter('hi'), true, 'hi'],
        [createFilter(), true, null],
        [createFilter(3, 'name', 'custom_name'), false, 'name'],
        [createFilter(3, '  ', 'custom_name'), false, '3'],
    ]

    paramsToExpected.forEach(([filter, isCustom, expected]) => {
        it(`expect "${expected}" for Filter<custom_name="${filter.custom_name}", name="${filter.name}", id="${filter.id}">`, () => {
            expect(getDisplayNameFromEntityFilter(filter, isCustom)).toEqual(expected)
        })
    })
})

const createEventsNode = (id?: Entity['id'], name?: string, custom_name?: string): EventsNode => {
    return {
        kind: NodeKind.EventsNode,
        custom_name,
        name,
        event: id ? String(id) : undefined,
    }
}

const createActionsNode = (id?: Entity['id'], name?: string, custom_name?: string): ActionsNode => {
    return {
        kind: NodeKind.ActionsNode,
        custom_name,
        name,
        id: Number(id),
    }
}

describe('getDisplayNameFromEntityNode()', () => {
    const paramsToExpected: [EventsNode | ActionsNode, boolean, string | null][] = [
        [createEventsNode(3, 'name', 'custom_name'), true, 'custom_name'],
        [createEventsNode(3, 'name', ''), true, 'name'],
        [createEventsNode(3, 'name', '    '), true, 'name'],
        [createEventsNode(3, 'name'), true, 'name'],
        [createEventsNode(3, '', ''), true, '3'],
        [createEventsNode(3, '  ', '    '), true, '3'],
        [createEventsNode(3), true, '3'],
        [createEventsNode('hi'), true, 'hi'],
        [createEventsNode(), true, null],
        [createEventsNode(3, 'name', 'custom_name'), false, 'name'],
        [createEventsNode(3, '  ', 'custom_name'), false, '3'],

        [createActionsNode(3, 'name', 'custom_name'), true, 'custom_name'],
        [createActionsNode(3, 'name', ''), true, 'name'],
        [createActionsNode(3, 'name', '    '), true, 'name'],
        [createActionsNode(3, 'name'), true, 'name'],
        [createActionsNode(3, '', ''), true, '3'],
        [createActionsNode(3, '  ', '    '), true, '3'],
        [createActionsNode(3), true, '3'],
        [createActionsNode(), true, null],
        [createActionsNode(3, 'name', 'custom_name'), false, 'name'],
        [createActionsNode(3, '  ', 'custom_name'), false, '3'],
    ]

    paramsToExpected.forEach(([node, isCustom, expected]) => {
        if (isEventsNode(node)) {
            it(`expect "${expected}" for EventsNode<custom_name="${node.custom_name}", name="${node.name}", event="${node.event}">, isCustom<${isCustom}>`, () => {
                expect(getDisplayNameFromEntityNode(node, isCustom)).toEqual(expected)
            })
        } else {
            it(`expect "${expected}" for ActionsNode<custom_name="${node.custom_name}", name="${node.name}", id="${node.id}">, isCustom<${isCustom}`, () => {
                expect(getDisplayNameFromEntityNode(node, isCustom)).toEqual(expected)
            })
        }
    })
})

describe('extractObjectDiffKeys()', () => {
    const testCases: [string, FilterType, FilterType, string, Record<string, any>][] = [
        [
            'one value',
            { insight: InsightType.TRENDS },
            { insight: InsightType.FUNNELS },
            '',
            { changed_insight: InsightType.TRENDS },
        ],
        [
            'multiple values',
            { insight: InsightType.TRENDS, date_from: '-7d' },
            { insight: InsightType.FUNNELS, date_from: '-7d' },
            '',
            { changed_insight: InsightType.TRENDS },
        ],
        [
            'nested event',
            { insight: InsightType.TRENDS, events: [{ name: 'pageview', math: 'total' }] },
            { insight: InsightType.TRENDS, events: [{ name: 'pageview', math: 'dau' }] },
            '',
            { changed_event_0_math: 'total' },
        ],
        [
            'nested event multiple',
            {
                insight: InsightType.TRENDS,
                events: [
                    { name: 'pageview', math: 'dau' },
                    { name: 'pageview', math: 'total' },
                ],
            },
            {
                insight: InsightType.TRENDS,
                events: [
                    { name: 'pageview', math: 'dau' },
                    { name: 'pageview', math: 'dau' },
                ],
            },
            '',
            { changed_event_1_math: 'total' },
        ],
        [
            'nested action',
            { insight: InsightType.TRENDS, actions: [{ name: 'pageview', math: 'total' }] },
            { insight: InsightType.TRENDS, actions: [{ name: 'pageview', math: 'dau' }] },
            '',
            { changed_action_0_math: 'total' },
        ],
        [
            'nested action',
            { insight: InsightType.TRENDS, actions: undefined, events: [] },
            { insight: InsightType.TRENDS, actions: [], events: undefined },
            '',
            {},
        ],
        [
            'nested action',
            { insight: InsightType.TRENDS, actions: undefined, events: [] },
            { insight: InsightType.TRENDS, actions: [{ name: 'pageview', math: 'dau ' }], events: undefined },
            '',
            { changed_actions_length: 0 },
        ],
    ]

    testCases.forEach(([testName, oldFilter, newFilter, prefix, expected]) => {
        it(`expect ${JSON.stringify(expected)} for ${testName}`, () => {
            expect(extractObjectDiffKeys(oldFilter, newFilter, prefix)).toEqual(expected)
        })
    })
})

describe('formatAggregationValue', () => {
    it('safely handles null', () => {
        const fakeRenderCount = (x: number): string => String(x)
        const noOpFormatProperty = jest.fn((_, y) => y)
        const actual = formatAggregationValue('some name', null, fakeRenderCount, noOpFormatProperty)
        expect(actual).toEqual('-')
    })

    it('uses render count when there is a value and property format is a no-op', () => {
        const fakeRenderCount = (x: number): string =>
            formatAggregationAxisValue({ aggregationAxisFormat: 'duration' }, x)
        const noOpFormatProperty = jest.fn((_, y) => y)
        const actual = formatAggregationValue('some name', 500, fakeRenderCount, noOpFormatProperty)
        expect(actual).toEqual('8m 20s')
    })

    it('uses render count when there is a value and property format converts number to string', () => {
        const fakeRenderCount = (x: number): string =>
            formatAggregationAxisValue({ aggregationAxisFormat: 'duration' }, x)
        const noOpFormatProperty = jest.fn((_, y) => String(y))
        const actual = formatAggregationValue('some name', 500, fakeRenderCount, noOpFormatProperty)
        expect(actual).toEqual('8m 20s')
    })
})

describe('formatBreakdownLabel()', () => {
    const identity = (_breakdown: any, breakdown_value: any): any => breakdown_value

    const cohort = {
        id: 5,
        name: 'some cohort',
    }

    it('handles cohort breakdowns', () => {
        const breakdownFilter1: BreakdownFilter = {
            breakdown: [cohort.id],
            breakdown_type: 'cohort',
        }
        expect(formatBreakdownLabel(cohort.id, breakdownFilter1, [cohort as any], identity)).toEqual(cohort.name)

        const breakdownFilter2: BreakdownFilter = {
            breakdown: [3],
            breakdown_type: 'cohort',
        }
        expect(formatBreakdownLabel(3, breakdownFilter2, [], identity)).toEqual('3')
    })

    it('handles cohort breakdowns with all users', () => {
        const breakdownFilter1: BreakdownFilter = {
            breakdown: ['all'],
            breakdown_type: 'cohort',
        }
        expect(formatBreakdownLabel('all', breakdownFilter1, [], identity)).toEqual('All Users')

        const breakdownFilter2: BreakdownFilter = {
            breakdown: [0],
            breakdown_type: 'cohort',
        }
        expect(formatBreakdownLabel(0, breakdownFilter2, [], identity)).toEqual('All Users')
    })

    it('handles histogram breakdowns', () => {
        const breakdownFilter: BreakdownFilter = {
            breakdown: '$browser_version',
            breakdown_type: 'event',
            breakdown_histogram_bin_count: 10,
        }
        expect(formatBreakdownLabel('[124.8,125.01]', breakdownFilter, [], identity)).toEqual('124.8 – 125.01')
    })

    it('handles histogram breakdowns for start and end values', () => {
        const breakdownFilter: BreakdownFilter = {
            breakdown: '$browser_version',
            breakdown_type: 'event',
            breakdown_histogram_bin_count: 10,
        }
        expect(formatBreakdownLabel('[124.8,124.8]', breakdownFilter, [], identity)).toEqual('124.8')
    })

    it('handles histogram breakdowns for "other" value', () => {
        const breakdownFilter: BreakdownFilter = {
            breakdown: '$browser_version',
            breakdown_type: 'event',
            breakdown_histogram_bin_count: 10,
        }
        expect(formatBreakdownLabel('$$_posthog_breakdown_other_$$', breakdownFilter, [], identity)).toEqual(
            'Other (i.e. all remaining values)'
        )
    })

    it('handles histogram breakdowns for "null" value', () => {
        const breakdownFilter: BreakdownFilter = {
            breakdown: '$browser_version',
            breakdown_type: 'event',
            breakdown_histogram_bin_count: 10,
        }
        expect(formatBreakdownLabel('$$_posthog_breakdown_null_$$', breakdownFilter, [], identity)).toEqual(
            'None (i.e. no value)'
        )
    })

    it('handles numeric breakdowns', () => {
        const breakdownFilter: BreakdownFilter = {
            breakdown: 'coolness_factor',
            breakdown_type: 'event',
        }
        expect(formatBreakdownLabel(42, breakdownFilter, [], identity)).toEqual('42')
    })

    it('handles numeric breakdowns for "other" value', () => {
        const breakdownFilter: BreakdownFilter = {
            breakdown: 'coolness_factor',
            breakdown_type: 'event',
        }
        expect(formatBreakdownLabel(9007199254740991, breakdownFilter, [], identity)).toEqual(
            'Other (i.e. all remaining values)'
        )
    })

    it('handles numeric breakdowns for "null" value', () => {
        const breakdownFilter: BreakdownFilter = {
            breakdown: 'coolness_factor',
            breakdown_type: 'event',
        }
        expect(formatBreakdownLabel(9007199254740990, breakdownFilter, [], identity)).toEqual('None (i.e. no value)')
    })

    it('handles string breakdowns', () => {
        const breakdownFilter: BreakdownFilter = {
            breakdown: 'demographic',
            breakdown_type: 'event',
        }
        expect(formatBreakdownLabel('millenial', breakdownFilter, [], identity)).toEqual('millenial')
    })

    it('handles string breakdowns for "other" value', () => {
        const breakdownFilter: BreakdownFilter = {
            breakdown: 'demographic',
            breakdown_type: 'event',
        }
        expect(formatBreakdownLabel('$$_posthog_breakdown_other_$$', breakdownFilter, [], identity)).toEqual(
            'Other (i.e. all remaining values)'
        )
    })

    it('handles string breakdowns for "null" value', () => {
        const breakdownFilter: BreakdownFilter = {
            breakdown: 'demographic',
            breakdown_type: 'event',
        }
        expect(formatBreakdownLabel('$$_posthog_breakdown_null_$$', breakdownFilter, [], identity)).toEqual(
            'None (i.e. no value)'
        )
    })

    it('handles multi-breakdowns', () => {
        const breakdownFilter: BreakdownFilter = {
            breakdown: ['demographic', '$browser'],
            breakdown_type: 'event',
        }
        expect(formatBreakdownLabel(['millenial', 'Chrome'], breakdownFilter, [], identity)).toEqual(
            'millenial::Chrome'
        )
    })

    it('handles multiple breakdowns', () => {
        const breakdownFilter: BreakdownFilter = {
            breakdowns: [
                {
                    property: 'demographic',
                    type: 'event',
                },
                {
                    property: '$browser',
                    type: 'event',
                },
            ],
            breakdown: 'fallback',
        }

        expect(formatBreakdownLabel(['Engineers', 'Chrome'], breakdownFilter, [], identity, 1)).toEqual(
            'Engineers::Chrome'
        )
        expect(formatBreakdownLabel([10, 'Chrome'], breakdownFilter, [], identity, 2)).toEqual('10::Chrome')
        expect(formatBreakdownLabel([10, 'Chrome'], breakdownFilter, [], () => '10s', 0)).toEqual('10s::Chrome')
    })

    it('handles a breakdown value of a multiple breakdown', () => {
        const breakdownFilter: BreakdownFilter = {
            breakdowns: [
                {
                    property: 'demographic',
                    type: 'event',
                },
                {
                    property: '$browser',
                    type: 'event',
                },
            ],
            breakdown: 'fallback',
        }

        expect(formatBreakdownLabel('Chrome', breakdownFilter, [], identity, 1)).toEqual('Chrome')
        expect(formatBreakdownLabel(10, breakdownFilter, [], identity, 2)).toEqual('10')
        expect(formatBreakdownLabel(10, breakdownFilter, [], () => '10s', 0)).toEqual('10s')
    })

    it('handles stringified numbers', () => {
        const formatter = (_breakdown: any, v: any): any => `${v}s`

        const breakdownFilter1: BreakdownFilter = {
            breakdown: '$session_duration',
            breakdown_type: 'session',
        }
        expect(formatBreakdownLabel('661', breakdownFilter1, undefined, formatter)).toEqual('661s')

        const breakdownFilter2: BreakdownFilter = {
            breakdowns: [
                {
                    property: '$session_duration',
                    type: 'session',
                },
            ],
        }
        expect(formatBreakdownLabel('661', breakdownFilter2, undefined, formatter, 0)).toEqual('661s')
    })

    it('handles large stringified numbers', () => {
        const formatter = (_breakdown: any, v: any): any => `${v}s`

        const breakdownFilter1: BreakdownFilter = {
            breakdown: '$session_duration',
            breakdown_type: 'session',
        }
        expect(formatBreakdownLabel('661', breakdownFilter1, undefined, formatter)).toEqual('661s')

        const breakdownFilter2: BreakdownFilter = {
            breakdowns: [
                {
                    property: '$session_duration',
                    type: 'session',
                },
            ],
        }
        expect(formatBreakdownLabel('987654321012345678', breakdownFilter2, undefined, formatter, 0)).toEqual(
            '987654321012345678s'
        )
    })

    it('handles array first', () => {
        const formatter = (_: any, value: any, type: any): any => (type === 'session' ? `${value}s` : value)

        const breakdownFilter1: BreakdownFilter = {
            breakdown: '$session_duration',
            breakdown_type: 'session',
        }
        expect(formatBreakdownLabel(['661'], breakdownFilter1, undefined, formatter)).toEqual('661s')

        const breakdownFilter2: BreakdownFilter = {
            breakdowns: [
                {
                    property: '$session_duration',
                    type: 'session',
                },
            ],
        }
        expect(formatBreakdownLabel('661', breakdownFilter2, undefined, formatter, 0)).toEqual('661s')
    })

    it('handles group breakdowns', () => {
        const formatter = jest.fn((_, v) => v)

        const breakdownFilter1: BreakdownFilter = {
            breakdown: 'name',
            breakdown_group_type_index: 0,
            breakdown_type: 'group',
        }
        expect(formatBreakdownLabel('661', breakdownFilter1, undefined, formatter)).toEqual('661')
        expect(formatter).toHaveBeenCalledWith('name', 661, 'group', 0)

        formatter.mockClear()

        const breakdownFilter2: BreakdownFilter = {
            breakdowns: [{ property: 'name', type: 'group', group_type_index: 0 }],
        }
        expect(formatBreakdownLabel(['661'], breakdownFilter2, undefined, formatter, 0)).toEqual('661')
        expect(formatter).toHaveBeenCalledWith('name', 661, 'group', 0)

        formatter.mockClear()

        const breakdownFilter3: BreakdownFilter = {
            breakdowns: [
                { property: 'name', type: 'group', group_type_index: 0 },
                { property: 'test', type: 'group', group_type_index: 1 },
            ],
        }
        expect(formatBreakdownLabel(['661', '662'], breakdownFilter3, undefined, formatter, 0)).toEqual('661::662')
        expect(formatter).toHaveBeenNthCalledWith(1, 'name', 661, 'group', 0)
        expect(formatter).toHaveBeenNthCalledWith(2, 'test', 662, 'group', 1)
    })
})

describe('formatBreakdownType()', () => {
    it('handles regular breakdowns', () => {
        const breakdownFilter: BreakdownFilter = {
            breakdown_type: 'event',
            breakdown: '$current_url',
            breakdown_normalize_url: true,
        }

        expect(formatBreakdownType(breakdownFilter)).toEqual('$current_url')
    })

    it('handles cohort breakdowns', () => {
        const breakdownFilter: BreakdownFilter = {
            breakdown_type: 'cohort',
            breakdown: ['all', 1],
        }

        expect(formatBreakdownType(breakdownFilter)).toEqual('Cohort')
    })
})

describe('getTrendDatasetKey()', () => {
    it('handles a simple insight', () => {
        const dataset: Partial<IndexedTrendResult> = {
            label: '$pageview',
            action: {
                id: '$pageview',
                type: 'events',
                order: 0,
            },
        }

        expect(getTrendDatasetKey(dataset as IndexedTrendResult)).toEqual('{"series":0}')
    })

    it('handles insights with breakdowns', () => {
        const dataset: Partial<IndexedTrendResult> = {
            label: 'Opera::US',
            action: {
                id: '$pageview',
                type: 'events',
                order: 0,
            },
            breakdown_value: ['Opera', 'US'],
        }

        expect(getTrendDatasetKey(dataset as IndexedTrendResult)).toEqual(
            '{"series":0,"breakdown_value":["Opera","US"]}'
        )
    })

    it('handles insights with compare against previous', () => {
        const dataset: Partial<IndexedTrendResult> = {
            label: '$pageview',
            action: {
                id: '$pageview',
                type: 'events',
                order: 0,
            },
            compare: true,
            compare_label: CompareLabelType.Current,
        }

        expect(getTrendDatasetKey(dataset as IndexedTrendResult)).toEqual('{"series":0,"compare_label":"current"}')
    })

    it('handles insights with formulas', () => {
        const dataset: Partial<IndexedTrendResult> = {
            label: 'Formula (A+B)',
            action: undefined,
        }

        expect(getTrendDatasetKey(dataset as IndexedTrendResult)).toEqual('{"series":"formula"}')
    })

    it('handles insights with non-array breakdown values', () => {
        const dataset: Partial<IndexedTrendResult> = {
            label: 'Opera',
            action: {
                id: '$pageview',
                type: 'events',
                order: 0,
            },
            breakdown_value: 'Opera',
        }

        expect(getTrendDatasetKey(dataset as IndexedTrendResult)).toEqual('{"series":0,"breakdown_value":["Opera"]}')
    })
})

describe('compareTopLevelSections()', () => {
    it('compares top-level sections', () => {
        const obj1: InsightQueryNode = {
            kind: NodeKind.TrendsQuery,
            series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
            interval: 'day',
        }
        const obj2: InsightQueryNode = {
            kind: NodeKind.FunnelsQuery,
            series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
            interval: 'day',
        }

        expect(compareInsightTopLevelSections(obj1, obj2)).toEqual(['Insight type'])
    })

    it('compares source fields', () => {
        const obj1: InsightQueryNode = {
            kind: NodeKind.TrendsQuery,
            series: [],
            interval: 'day',
        }
        const obj2: InsightQueryNode = {
            kind: NodeKind.TrendsQuery,
            series: [],
            interval: 'week',
        }

        expect(compareInsightTopLevelSections(obj1, obj2)).toEqual(['Interval'])
    })

    it('compares multiple source fields', () => {
        const obj1: InsightQueryNode = {
            kind: NodeKind.TrendsQuery,
            series: [],
            interval: 'day',
            breakdownFilter: undefined,
            dateRange: { date_from: '-7d' },
        }
        const obj2: InsightQueryNode = {
            kind: NodeKind.TrendsQuery,
            series: [],
            interval: 'week',
            breakdownFilter: { breakdown: '$browser', breakdown_type: 'event' },
            dateRange: { date_from: '-30d' },
        }

        expect(compareInsightTopLevelSections(obj1, obj2)).toEqual(['Breakdowns', 'Date range', 'Interval'])
    })

    it('handles unknown source fields', () => {
        const obj1 = { kind: NodeKind.TrendsQuery, series: [], unknownField: 'value1' } as any
        const obj2 = { kind: NodeKind.TrendsQuery, series: [], unknownField: 'value2' } as any

        expect(compareInsightTopLevelSections(obj1, obj2)).toEqual(['unknownField'])
    })

    it('handles nested objects in source fields', () => {
        const obj1: InsightQueryNode = {
            kind: NodeKind.TrendsQuery,
            series: [],
            breakdownFilter: { breakdown: '$browser', breakdown_type: 'event' },
        }
        const obj2: InsightQueryNode = {
            kind: NodeKind.TrendsQuery,
            series: [],
            breakdownFilter: { breakdown: '$os', breakdown_type: 'event' },
        }

        expect(compareInsightTopLevelSections(obj1, obj2)).toEqual(['Breakdowns'])
    })

    it('handles arrays in source fields', () => {
        const obj1: InsightQueryNode = {
            kind: NodeKind.TrendsQuery,
            series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
        }
        const obj2: InsightQueryNode = {
            kind: NodeKind.TrendsQuery,
            series: [
                { kind: NodeKind.EventsNode, event: '$pageview' },
                { kind: NodeKind.EventsNode, event: '$autocapture' },
            ],
        }

        expect(compareInsightTopLevelSections(obj1, obj2)).toEqual(['Series'])
    })

    it('returns empty array when no differences', () => {
        const obj1: InsightQueryNode = {
            kind: NodeKind.TrendsQuery,
            series: [],
            interval: 'day',
        }
        const obj2: InsightQueryNode = {
            kind: NodeKind.TrendsQuery,
            series: [],
            interval: 'day',
        }

        expect(compareInsightTopLevelSections(obj1, obj2)).toEqual([])
    })

    it('handles arrays with same elements in different order', () => {
        const obj1: InsightQueryNode = {
            kind: NodeKind.TrendsQuery,
            series: [
                { kind: NodeKind.EventsNode, event: '$pageview' },
                { kind: NodeKind.EventsNode, event: '$autocapture' },
            ],
        }
        const obj2: InsightQueryNode = {
            kind: NodeKind.TrendsQuery,
            series: [
                { kind: NodeKind.EventsNode, event: '$autocapture' },
                { kind: NodeKind.EventsNode, event: '$pageview' },
            ],
        }

        expect(compareInsightTopLevelSections(obj1, obj2)).toEqual([])
    })

    it('handles null/undefined objects', () => {
        expect(
            compareInsightTopLevelSections(null as any, { kind: NodeKind.TrendsQuery, series: [] } as InsightQueryNode)
        ).toEqual(['Insight type'])
        expect(
            compareInsightTopLevelSections({ kind: NodeKind.TrendsQuery, series: [] } as InsightQueryNode, null as any)
        ).toEqual(['Insight type'])
        expect(compareInsightTopLevelSections(null as any, null as any)).toEqual([])
    })
})
