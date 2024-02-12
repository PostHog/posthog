import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import {
    extractObjectDiffKeys,
    formatAggregationValue,
    formatBreakdownLabel,
    formatBreakdownType,
    getDisplayNameFromEntityFilter,
    getDisplayNameFromEntityNode,
} from 'scenes/insights/utils'

import { ActionsNode, BreakdownFilter, EventsNode, NodeKind } from '~/queries/schema'
import { isEventsNode } from '~/queries/utils'
import { Entity, EntityFilter, FilterType, InsightType } from '~/types'

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
    const identity = (x: any): any => x

    const cohort = {
        id: 5,
        name: 'some cohort',
    }

    it('handles cohort breakdowns', () => {
        expect(formatBreakdownLabel([cohort as any], identity, cohort.id, [cohort.id], 'cohort')).toEqual(cohort.name)
        expect(formatBreakdownLabel([], identity, 3, [3], 'cohort')).toEqual('3')
    })

    it('handles cohort breakdowns with all users', () => {
        expect(formatBreakdownLabel([], identity, 'all', ['all'], 'cohort')).toEqual('All Users')
        expect(formatBreakdownLabel([], identity, 0, [0], 'cohort')).toEqual('All Users')
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
