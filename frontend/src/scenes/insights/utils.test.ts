import { CohortType, Entity, EntityFilter, FilterLogicalOperator, FilterType, InsightType, PathType } from '~/types'
import {
    extractObjectDiffKeys,
    formatAggregationValue,
    getDisplayNameFromEntityFilter,
    summarizeInsightFilters,
} from 'scenes/insights/utils'
import { BASE_MATH_DEFINITIONS, MathDefinition, PROPERTY_MATH_DEFINITIONS } from 'scenes/trends/mathsLogic'
import { RETENTION_FIRST_TIME, RETENTION_RECURRING } from 'lib/constants'

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

describe('summarizeInsightFilters()', () => {
    const aggregationLabel = (groupTypeIndex: number | null | undefined): { singular: string; plural: string } =>
        groupTypeIndex != undefined
            ? {
                  singular: 'organization',
                  plural: 'organizations',
              }
            : { singular: 'user', plural: 'users' }
    const cohortIdsMapped: Partial<Record<CohortType['id'], CohortType>> = {
        1: {
            id: 1,
            name: 'Poles',
            filters: { properties: { id: '1', type: FilterLogicalOperator.Or, values: [] } },
            groups: [],
        },
    }
    const mathDefinitions: Record<string, MathDefinition> = {
        ...BASE_MATH_DEFINITIONS,
        'unique_group::0': {
            shortName: 'unique organizations',
        } as unknown as MathDefinition,
        ...PROPERTY_MATH_DEFINITIONS,
    }

    it('summarizes a Trends insight with five different series', () => {
        expect(
            summarizeInsightFilters(
                {
                    insight: InsightType.TRENDS,
                    events: [
                        {
                            id: '$pageview',
                            name: '$pageview',
                            math: 'dau',
                            order: 0,
                        },
                        {
                            id: '$rageclick',
                            name: '$rageclick',
                            math: 'monthly_active',
                            order: 1,
                        },
                        {
                            id: 'purchase',
                            name: 'purchase',
                            math: 'sum',
                            math_property: 'price',
                            order: 3,
                        },
                        {
                            id: '$pageview',
                            name: '$pageview',
                            math: 'unique_group',
                            math_group_type_index: 0,
                            order: 4,
                        },
                        {
                            id: '$autocapture',
                            name: '$autocapture',
                            math: 'unique_group',
                            math_group_type_index: 11, // Non-existent group
                            order: 5,
                        },
                    ],
                    actions: [
                        {
                            id: 1,
                            name: 'Random action',
                            math: 'total',
                            order: 2,
                        },
                    ],
                },
                aggregationLabel,
                cohortIdsMapped,
                mathDefinitions
            )
        ).toEqual(
            "Pageview unique users & Rageclick MAUs & Random action count & purchase's price sum & Pageview unique organizations & Autocapture unique groups"
        )
    })

    it('summarizes a Trends insight with no series', () => {
        expect(
            summarizeInsightFilters(
                {
                    insight: InsightType.TRENDS,
                },
                aggregationLabel,
                cohortIdsMapped,
                mathDefinitions
            )
        ).toEqual('')
    })

    it('summarizes a Trends insight with event property breakdown', () => {
        expect(
            summarizeInsightFilters(
                {
                    insight: InsightType.TRENDS,
                    events: [
                        {
                            id: '$pageview',
                            name: '$pageview',
                            math: 'dau',
                            order: 0,
                        },
                    ],
                    breakdown_type: 'event',
                    breakdown: '$browser',
                },
                aggregationLabel,
                cohortIdsMapped,
                mathDefinitions
            )
        ).toEqual("Pageview unique users by event's Browser")
    })

    it('summarizes a Trends insight with cohort breakdown', () => {
        expect(
            summarizeInsightFilters(
                {
                    insight: InsightType.TRENDS,
                    events: [
                        {
                            id: '$pageview',
                            name: '$pageview',
                            order: 0,
                        },
                        {
                            id: '$pageview',
                            name: '$pageview',
                            math: 'dau',
                            order: 0,
                        },
                    ],
                    breakdown_type: 'cohort',
                    breakdown: ['all', 1],
                },
                aggregationLabel,
                cohortIdsMapped,
                mathDefinitions
            )
        ).toEqual('Pageview count & Pageview unique users, by cohorts: all users, Poles')
    })

    it('summarizes a Trends insight with a formula', () => {
        expect(
            summarizeInsightFilters(
                {
                    insight: InsightType.TRENDS,
                    events: [
                        {
                            id: '$pageview',
                            name: '$pageview',
                            math: 'dau',
                            order: 0,
                        },
                    ],
                    actions: [
                        {
                            id: 1,
                            name: 'Random action',
                            math: 'total',
                            order: 2,
                        },
                    ],
                    formula: '(A + B) / 100',
                },
                aggregationLabel,
                cohortIdsMapped,
                mathDefinitions
            )
        ).toEqual('(A + B) / 100 on A. Pageview unique users & B. Random action count')
    })

    it('summarizes a user-based Funnels insight with 3 steps', () => {
        expect(
            summarizeInsightFilters(
                {
                    insight: InsightType.FUNNELS,
                    events: [
                        {
                            id: '$pageview',
                            name: '$pageview',
                            order: 0,
                        },
                        {
                            id: 'random_event',
                            name: 'random_event',
                            order: 1,
                        },
                    ],
                    actions: [
                        {
                            id: 1,
                            name: 'Random action',
                            order: 2,
                        },
                    ],
                },
                aggregationLabel,
                cohortIdsMapped,
                mathDefinitions
            )
        ).toEqual('Pageview → random_event → Random action user conversion rate')
    })

    it('summarizes an organization-based Funnels insight with 2 steps and a breakdown', () => {
        expect(
            summarizeInsightFilters(
                {
                    insight: InsightType.FUNNELS,
                    events: [
                        {
                            id: '$pageview',
                            name: '$pageview',
                            order: 0,
                        },
                        {
                            id: 'random_event',
                            name: 'random_event',
                            order: 1,
                        },
                    ],
                    aggregation_group_type_index: 0,
                    breakdown_type: 'person',
                    breakdown: 'some_prop',
                },
                aggregationLabel,
                cohortIdsMapped,
                mathDefinitions
            )
        ).toEqual("Pageview → random_event organization conversion rate by person's some_prop")
    })

    it('summarizes a user first-time Retention insight with the same event for cohortizing and returning', () => {
        expect(
            summarizeInsightFilters(
                {
                    insight: InsightType.RETENTION,
                    target_entity: {
                        id: '$autocapture',
                        name: '$autocapture',
                        type: 'event',
                    },
                    returning_entity: {
                        id: '$autocapture',
                        name: '$autocapture',
                        type: 'event',
                    },
                    retention_type: RETENTION_FIRST_TIME,
                },
                aggregationLabel,
                cohortIdsMapped,
                mathDefinitions
            )
        ).toEqual('Retention of users based on doing Autocapture for the first time and returning with the same event')
    })

    it('summarizes an organization recurring Retention insight with the different events for cohortizing and returning', () => {
        expect(
            summarizeInsightFilters(
                {
                    insight: InsightType.RETENTION,
                    target_entity: {
                        id: 'purchase',
                        name: 'purchase',
                        type: 'event',
                    },
                    returning_entity: {
                        id: '$pageview',
                        name: '$pageview',
                        type: 'event',
                    },
                    retention_type: RETENTION_RECURRING,
                    aggregation_group_type_index: 0,
                },
                aggregationLabel,
                cohortIdsMapped,
                mathDefinitions
            )
        ).toEqual('Retention of organizations based on doing purchase recurringly and returning with Pageview')
    })

    it('summarizes a Paths insight based on all events', () => {
        expect(
            summarizeInsightFilters(
                {
                    insight: InsightType.PATHS,
                    include_event_types: [PathType.PageView, PathType.Screen, PathType.CustomEvent],
                },
                aggregationLabel,
                cohortIdsMapped,
                mathDefinitions
            )
        ).toEqual('User paths based on all events')
    })

    it('summarizes a Paths insight based on all events (empty include_event_types case)', () => {
        expect(
            summarizeInsightFilters(
                {
                    insight: InsightType.PATHS,
                    include_event_types: [],
                },
                aggregationLabel,
                cohortIdsMapped,
                mathDefinitions
            )
        ).toEqual('User paths based on all events')
    })

    it('summarizes a Paths insight based on pageviews with start and end points', () => {
        expect(
            summarizeInsightFilters(
                {
                    insight: InsightType.PATHS,
                    include_event_types: [PathType.PageView],
                    start_point: '/landing-page',
                    end_point: '/basket',
                },
                aggregationLabel,
                cohortIdsMapped,
                mathDefinitions
            )
        ).toEqual('User paths based on page views starting at /landing-page and ending at /basket')
    })

    it('summarizes a Stickiness insight with a user-based series and an organization-based one', () => {
        expect(
            summarizeInsightFilters(
                {
                    insight: InsightType.STICKINESS,
                    events: [
                        {
                            id: '$pageview',
                            name: '$pageview',
                            type: 'event',
                            order: 1,
                        },
                    ],
                    actions: [
                        {
                            id: 1,
                            name: 'Random action',
                            type: 'action',
                            order: 0,
                            math: 'unique_group',
                            math_group_type_index: 0,
                        },
                    ],
                },
                aggregationLabel,
                cohortIdsMapped,
                mathDefinitions
            )
        ).toEqual('Organization stickiness based on Random action & user stickiness based on Pageview')
    })

    it('summarizes a Lifecycle insight', () => {
        expect(
            summarizeInsightFilters(
                {
                    insight: InsightType.LIFECYCLE,
                    events: [
                        {
                            id: '$rageclick',
                            name: '$rageclick',
                            type: 'event',
                            order: 1,
                        },
                    ],
                },
                aggregationLabel,
                cohortIdsMapped,
                mathDefinitions
            )
        ).toEqual('User lifecycle based on Rageclick')
    })
})

describe('formatAggregationValue', () => {
    it('safely handles null', () => {
        const fakeRenderCount = (x: number): string => String(x)
        const noOpFormatProperty = jest.fn((_, y) => y)
        const actual = formatAggregationValue('some name', null, fakeRenderCount, noOpFormatProperty)
        expect(actual).toEqual('-')
    })
})
