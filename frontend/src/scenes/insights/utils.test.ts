import {
    BaseMathType,
    CohortType,
    CountPerActorMathType,
    Entity,
    EntityFilter,
    FilterLogicalOperator,
    FilterType,
    GroupMathType,
    InsightType,
    PathType,
    PropertyMathType,
} from '~/types'
import {
    extractObjectDiffKeys,
    formatAggregationValue,
    formatBreakdownLabel,
    getDisplayNameFromEntityFilter,
    getDisplayNameFromEntityNode,
    summariseInsight,
    summarizeInsightFilters,
    summarizeInsightQuery,
} from 'scenes/insights/utils'
import {
    BASE_MATH_DEFINITIONS,
    COUNT_PER_ACTOR_MATH_DEFINITIONS,
    MathCategory,
    MathDefinition,
    PROPERTY_MATH_DEFINITIONS,
} from 'scenes/trends/mathsLogic'
import { RETENTION_FIRST_TIME, RETENTION_RECURRING } from 'lib/constants'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { Noun } from '~/models/groupsModel'
import {
    ActionsNode,
    DataTableNode,
    EventsNode,
    FunnelsQuery,
    HogQLQuery,
    LifecycleQuery,
    NodeKind,
    PathsQuery,
    RecentPerformancePageViewNode,
    RetentionQuery,
    StickinessQuery,
    TimeToSeeDataWaterfallNode,
    TrendsQuery,
} from '~/queries/schema'
import { isEventsNode } from '~/queries/utils'

const aggregationLabel = (groupTypeIndex: number | null | undefined): Noun =>
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
        name: 'Unique organizations',
        shortName: 'unique organizations',
        description: 'Foo.',
        category: MathCategory.ActorCount,
    },
    ...PROPERTY_MATH_DEFINITIONS,
    ...COUNT_PER_ACTOR_MATH_DEFINITIONS,
}

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

describe('summarizeInsightFilters()', () => {
    const aggregationLabel = (groupTypeIndex: number | null | undefined): Noun =>
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
            name: 'Unique organizations',
            shortName: 'unique organizations',
            description: 'Foo.',
            category: MathCategory.ActorCount,
        },
        ...PROPERTY_MATH_DEFINITIONS,
        ...COUNT_PER_ACTOR_MATH_DEFINITIONS,
    }

    it('summarizes a Trends insight with four event and actor count series', () => {
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
            'Pageview unique users & Rageclick MAUs & Random action count & Pageview unique organizations & Autocapture unique groups'
        )
    })

    it('summarizes a Trends insight with two property value and event count per actor series', () => {
        expect(
            summarizeInsightFilters(
                {
                    insight: InsightType.TRENDS,
                    events: [
                        {
                            id: 'purchase',
                            name: 'purchase',
                            math: 'sum',
                            math_property: 'price',
                            order: 1,
                        },
                    ],
                    actions: [
                        {
                            id: 1,
                            name: 'Random action',
                            math: 'avg_count_per_actor',
                            order: 0,
                        },
                    ],
                },
                aggregationLabel,
                cohortIdsMapped,
                mathDefinitions
            )
        ).toEqual("Random action count per user average & purchase's price sum")
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

describe('summarizeInsightQuery()', () => {
    it('summarizes a Trends insight with four event and actor count series', () => {
        const query: TrendsQuery = {
            kind: NodeKind.TrendsQuery,
            series: [
                {
                    kind: NodeKind.EventsNode,
                    event: '$pageview',
                    name: '$pageview',
                    math: BaseMathType.UniqueUsers,
                },
                {
                    kind: NodeKind.EventsNode,
                    event: '$rageclick',
                    name: '$rageclick',
                    math: BaseMathType.MonthlyActiveUsers,
                },
                {
                    kind: NodeKind.ActionsNode,
                    id: 1,
                    name: 'Random action',
                    math: BaseMathType.TotalCount,
                },
                {
                    kind: NodeKind.EventsNode,
                    event: '$pageview',
                    name: '$pageview',
                    math: GroupMathType.UniqueGroup,
                    math_group_type_index: 0,
                },
                {
                    kind: NodeKind.EventsNode,
                    event: '$autocapture',
                    name: '$autocapture',
                    math: GroupMathType.UniqueGroup,
                    math_group_type_index: 4, // Non-existent group
                },
            ],
        }

        const result = summarizeInsightQuery(query, aggregationLabel, cohortIdsMapped, mathDefinitions)

        expect(result).toEqual(
            'Pageview unique users & Rageclick MAUs & Random action count & Pageview unique organizations & Autocapture unique groups'
        )
    })

    it('summarizes a Trends insight with two property value and event count per actor series', () => {
        const query: TrendsQuery = {
            kind: NodeKind.TrendsQuery,
            series: [
                {
                    kind: NodeKind.ActionsNode,
                    id: 1,
                    name: 'Random action',
                    math: CountPerActorMathType.Average,
                },
                {
                    kind: NodeKind.EventsNode,
                    event: 'purchase',
                    name: 'purchase',
                    math: PropertyMathType.Sum,
                    math_property: 'price',
                },
            ],
        }

        const result = summarizeInsightQuery(query, aggregationLabel, cohortIdsMapped, mathDefinitions)

        expect(result).toEqual("Random action count per user average & purchase's price sum")
    })

    it('summarizes a Trends insight with no series', () => {
        const query: TrendsQuery = {
            kind: NodeKind.TrendsQuery,
            series: [],
        }

        const result = summarizeInsightQuery(query, aggregationLabel, cohortIdsMapped, mathDefinitions)

        expect(result).toEqual('')
    })

    it('summarizes a Trends insight with event property breakdown', () => {
        const query: TrendsQuery = {
            kind: NodeKind.TrendsQuery,
            series: [
                {
                    kind: NodeKind.EventsNode,
                    event: '$pageview',
                    name: '$pageview',
                    math: BaseMathType.UniqueUsers,
                },
            ],
            breakdown: {
                breakdown_type: 'event',
                breakdown: '$browser',
            },
        }

        const result = summarizeInsightQuery(query, aggregationLabel, cohortIdsMapped, mathDefinitions)

        expect(result).toEqual("Pageview unique users by event's Browser")
    })

    it('summarizes a Trends insight with cohort breakdown', () => {
        const query: TrendsQuery = {
            kind: NodeKind.TrendsQuery,
            series: [
                {
                    kind: NodeKind.EventsNode,
                    event: '$pageview',
                    name: '$pageview',
                },
                {
                    kind: NodeKind.EventsNode,
                    event: '$pageview',
                    name: '$pageview',
                    math: BaseMathType.UniqueUsers,
                },
            ],
            breakdown: {
                breakdown_type: 'cohort',
                breakdown: ['all', 1],
            },
        }

        const result = summarizeInsightQuery(query, aggregationLabel, cohortIdsMapped, mathDefinitions)

        expect(result).toEqual('Pageview count & Pageview unique users, by cohorts: all users, Poles')
    })

    it('summarizes a Trends insight with a formula', () => {
        const query: TrendsQuery = {
            kind: NodeKind.TrendsQuery,
            series: [
                {
                    kind: NodeKind.EventsNode,
                    event: '$pageview',
                    name: '$pageview',
                    math: BaseMathType.UniqueUsers,
                },
                {
                    kind: NodeKind.ActionsNode,
                    id: 1,
                    name: 'Random action',
                    math: BaseMathType.TotalCount,
                },
            ],
            trendsFilter: {
                formula: '(A + B) / 100',
            },
        }

        const result = summarizeInsightQuery(query, aggregationLabel, cohortIdsMapped, mathDefinitions)

        expect(result).toEqual('(A + B) / 100 on A. Pageview unique users & B. Random action count')
    })

    it('summarizes a user-based Funnels insight with 3 steps', () => {
        const query: FunnelsQuery = {
            kind: NodeKind.FunnelsQuery,
            series: [
                {
                    kind: NodeKind.EventsNode,
                    event: '$pageview',
                    name: '$pageview',
                },
                {
                    kind: NodeKind.EventsNode,
                    event: 'random_event',
                    name: 'random_event',
                },
                {
                    kind: NodeKind.ActionsNode,
                    id: 1,
                    name: 'Random action',
                },
            ],
        }

        const result = summarizeInsightQuery(query, aggregationLabel, cohortIdsMapped, mathDefinitions)

        expect(result).toEqual('Pageview → random_event → Random action user conversion rate')
    })

    it('summarizes an organization-based Funnels insight with 2 steps and a breakdown', () => {
        const query: FunnelsQuery = {
            kind: NodeKind.FunnelsQuery,
            series: [
                {
                    kind: NodeKind.EventsNode,
                    event: '$pageview',
                    name: '$pageview',
                },
                {
                    kind: NodeKind.EventsNode,
                    event: 'random_event',
                    name: 'random_event',
                },
            ],
            aggregation_group_type_index: 0,
            breakdown: {
                breakdown_type: 'person',
                breakdown: 'some_prop',
            },
        }

        const result = summarizeInsightQuery(query, aggregationLabel, cohortIdsMapped, mathDefinitions)

        expect(result).toEqual("Pageview → random_event organization conversion rate by person's some_prop")
    })

    it('summarizes a user first-time Retention insight with the same event for cohortizing and returning', () => {
        const query: RetentionQuery = {
            kind: NodeKind.RetentionQuery,
            retentionFilter: {
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
        }

        const result = summarizeInsightQuery(query, aggregationLabel, cohortIdsMapped, mathDefinitions)

        expect(result).toEqual(
            'Retention of users based on doing Autocapture for the first time and returning with the same event'
        )
    })

    it('summarizes an organization recurring Retention insight with the different events for cohortizing and returning', () => {
        const query: RetentionQuery = {
            kind: NodeKind.RetentionQuery,
            retentionFilter: {
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
            },
            aggregation_group_type_index: 0,
        }

        const result = summarizeInsightQuery(query, aggregationLabel, cohortIdsMapped, mathDefinitions)

        expect(result).toEqual(
            'Retention of organizations based on doing purchase recurringly and returning with Pageview'
        )
    })

    it('summarizes a Paths insight based on all events', () => {
        const query: PathsQuery = {
            kind: NodeKind.PathsQuery,
            pathsFilter: {
                include_event_types: [PathType.PageView, PathType.Screen, PathType.CustomEvent],
            },
        }

        const result = summarizeInsightQuery(query, aggregationLabel, cohortIdsMapped, mathDefinitions)

        expect(result).toEqual('User paths based on all events')
    })

    it('summarizes a Paths insight based on all events (empty include_event_types case)', () => {
        const query: PathsQuery = {
            kind: NodeKind.PathsQuery,
            pathsFilter: {
                include_event_types: [],
            },
        }

        const result = summarizeInsightQuery(query, aggregationLabel, cohortIdsMapped, mathDefinitions)

        expect(result).toEqual('User paths based on all events')
    })

    it('summarizes a Paths insight based on pageviews with start and end points', () => {
        const query: PathsQuery = {
            kind: NodeKind.PathsQuery,
            pathsFilter: {
                include_event_types: [PathType.PageView],
                start_point: '/landing-page',
                end_point: '/basket',
            },
        }

        const result = summarizeInsightQuery(query, aggregationLabel, cohortIdsMapped, mathDefinitions)

        expect(result).toEqual('User paths based on page views starting at /landing-page and ending at /basket')
    })

    it('summarizes a Stickiness insight with a user-based series and an organization-based one', () => {
        const query: StickinessQuery = {
            kind: NodeKind.StickinessQuery,
            series: [
                {
                    kind: NodeKind.ActionsNode,
                    id: 1,
                    name: 'Random action',
                    math_group_type_index: 0,
                },
                {
                    kind: NodeKind.EventsNode,
                    event: '$pageview',
                    name: '$pageview',
                },
            ],
        }

        const result = summarizeInsightQuery(query, aggregationLabel, cohortIdsMapped, mathDefinitions)

        expect(result).toEqual('Organization stickiness based on Random action & user stickiness based on Pageview')
    })

    it('summarizes a Lifecycle insight', () => {
        const query: LifecycleQuery = {
            kind: NodeKind.LifecycleQuery,
            series: [
                {
                    kind: NodeKind.EventsNode,
                    event: '$rageclick',
                    name: '$rageclick',
                },
            ],
        }

        const result = summarizeInsightQuery(query, aggregationLabel, cohortIdsMapped, mathDefinitions)

        expect(result).toEqual('User lifecycle based on Rageclick')
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
            formatAggregationAxisValue({ aggregation_axis_format: 'duration' }, x)
        const noOpFormatProperty = jest.fn((_, y) => y)
        const actual = formatAggregationValue('some name', 500, fakeRenderCount, noOpFormatProperty)
        expect(actual).toEqual('8m 20s')
    })

    it('uses render count when there is a value and property format converts number to string', () => {
        const fakeRenderCount = (x: number): string =>
            formatAggregationAxisValue({ aggregation_axis_format: 'duration' }, x)
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

describe('summarize data table query', () => {
    it('summarizes a simple query', () => {
        const query: DataTableNode = {
            kind: NodeKind.DataTableNode,
            source: {
                kind: NodeKind.EventsQuery,
                select: ['event'],
            },
        }

        const result = summariseInsight(true, query, aggregationLabel, cohortIdsMapped, mathDefinitions, {})

        expect(result).toEqual('event from events into a data table.')
    })

    it('summarizes a two column events query', () => {
        const query: DataTableNode = {
            kind: NodeKind.DataTableNode,
            source: {
                kind: NodeKind.EventsQuery,
                select: ['event', 'timestamp'],
            },
        }

        const result = summariseInsight(true, query, aggregationLabel, cohortIdsMapped, mathDefinitions, {})

        expect(result).toEqual('event, timestamp from events into a data table.')
    })

    it('summarizes using columns from top-level query', () => {
        const query: DataTableNode = {
            kind: NodeKind.DataTableNode,
            columns: ['event'],
            source: {
                kind: NodeKind.EventsQuery,
                select: ['event', 'timestamp'],
            },
        }

        const result = summariseInsight(true, query, aggregationLabel, cohortIdsMapped, mathDefinitions, {})

        expect(result).toEqual('event from events into a data table.')
    })

    it('summarizes using hiddencolumns from top-level query', () => {
        const query: DataTableNode = {
            kind: NodeKind.DataTableNode,
            hiddenColumns: ['event'],
            source: {
                kind: NodeKind.EventsQuery,
                select: ['event', 'timestamp'],
            },
        }

        const result = summariseInsight(true, query, aggregationLabel, cohortIdsMapped, mathDefinitions, {})

        expect(result).toEqual('timestamp from events into a data table.')
    })

    it('summarizes time to see data sessions listing', () => {
        const query: DataTableNode = {
            kind: NodeKind.DataTableNode,
            columns: ['session_id', 'session_start', 'session_end', 'duration_ms'],
            source: {
                kind: NodeKind.TimeToSeeDataSessionsQuery,
            },
        }

        const result = summariseInsight(true, query, aggregationLabel, cohortIdsMapped, mathDefinitions, {})

        expect(result).toEqual(
            'session_id, session_start, session_end, duration_ms from Time to See Data into a data table.'
        )
    })

    it('summarizes a single time to see data sessions listing', () => {
        const query: TimeToSeeDataWaterfallNode = {
            kind: NodeKind.TimeToSeeDataSessionsWaterfallNode,
            source: {
                kind: NodeKind.TimeToSeeDataQuery,
                sessionId: 'complete_me',
                sessionStart: 'iso_date',
                sessionEnd: 'iso_date',
            },
        }

        const result = summariseInsight(true, query, aggregationLabel, cohortIdsMapped, mathDefinitions, {})

        expect(result).toEqual('Waterfall chart for time to see session complete_me.')
    })

    it('summarizes a count table', () => {
        const query: DataTableNode = {
            kind: NodeKind.DataTableNode,
            full: true,
            source: {
                kind: NodeKind.EventsQuery,
                select: ['count()'],
            },
        }
        const result = summariseInsight(true, query, aggregationLabel, cohortIdsMapped, mathDefinitions, {})

        expect(result).toEqual('count() from events into a data table.')
    })

    it('avoids summarizing hogql', () => {
        const query: HogQLQuery = {
            kind: NodeKind.HogQLQuery,
            query: 'select event,\n          person.properties.email from events\n  where timestamp > now() - interval 1 day',
        }

        const result = summariseInsight(true, query, aggregationLabel, cohortIdsMapped, mathDefinitions, {})

        expect(result).toEqual('HogQL data table.')
    })

    it('summarizes a person query', () => {
        const query: DataTableNode = {
            kind: NodeKind.DataTableNode,
            columns: ['person', 'id', 'created_at', 'person.$delete'],
            source: {
                kind: NodeKind.PersonsNode,
            },
        }
        const result = summariseInsight(true, query, aggregationLabel, cohortIdsMapped, mathDefinitions, {})

        expect(result).toEqual('person, id, created_at, person.$delete from persons into a data table.')
    })

    it('summarizes a recent page views for performance query', () => {
        const query: RecentPerformancePageViewNode = {
            kind: NodeKind.RecentPerformancePageViewNode,
            dateRange: { date_from: '-7d' },
        }
        const result = summariseInsight(true, query, aggregationLabel, cohortIdsMapped, mathDefinitions, {})

        expect(result).toEqual('Recent page views with performance data.')
    })
})
