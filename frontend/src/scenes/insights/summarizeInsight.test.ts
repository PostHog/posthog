import { RETENTION_FIRST_OCCURRENCE_MATCHING_FILTERS, RETENTION_RECURRING } from 'lib/constants'
import { SummaryContext, summarizeInsight } from 'scenes/insights/summarizeInsight'
import {
    BASE_MATH_DEFINITIONS,
    COUNT_PER_ACTOR_MATH_DEFINITIONS,
    HOGQL_MATH_DEFINITIONS,
    MathCategory,
    MathDefinition,
    PROPERTY_MATH_DEFINITIONS,
} from 'scenes/trends/mathsLogic'

import { Noun } from '~/models/groupsModel'
import {
    DataTableNode,
    FunnelsQuery,
    InsightVizNode,
    LifecycleQuery,
    NodeKind,
    PathsQuery,
    RetentionQuery,
    StickinessQuery,
    TrendsQuery,
} from '~/queries/schema/schema-general'
import {
    BaseMathType,
    CohortType,
    CountPerActorMathType,
    FilterLogicalOperator,
    GroupMathType,
    PathType,
    PropertyMathType,
} from '~/types'

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
    ...HOGQL_MATH_DEFINITIONS,
}

const summaryContext: SummaryContext = {
    aggregationLabel,
    cohortsById: cohortIdsMapped,
    mathDefinitions,
}

describe('summarizing insights', () => {
    describe('summariseInsightQuery()', () => {
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

            const result = summarizeInsight(
                { kind: NodeKind.InsightVizNode, source: query } as InsightVizNode,
                summaryContext
            )

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

            const result = summarizeInsight(
                { kind: NodeKind.InsightVizNode, source: query } as InsightVizNode,
                summaryContext
            )

            expect(result).toEqual("Random action count per user average & purchase's price sum")
        })

        it('summarizes a Trends insight with no series', () => {
            const query: TrendsQuery = {
                kind: NodeKind.TrendsQuery,
                series: [],
            }

            const result = summarizeInsight(
                { kind: NodeKind.InsightVizNode, source: query } as InsightVizNode,
                summaryContext
            )

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
                breakdownFilter: {
                    breakdown_type: 'event',
                    breakdown: '$browser',
                },
            }

            const result = summarizeInsight(
                { kind: NodeKind.InsightVizNode, source: query } as InsightVizNode,
                summaryContext
            )

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
                breakdownFilter: {
                    breakdown_type: 'cohort',
                    breakdown: ['all', 1],
                },
            }

            const result = summarizeInsight(
                { kind: NodeKind.InsightVizNode, source: query } as InsightVizNode,
                summaryContext
            )

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

            const result = summarizeInsight(
                { kind: NodeKind.InsightVizNode, source: query } as InsightVizNode,
                summaryContext
            )

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

            const result = summarizeInsight(
                { kind: NodeKind.InsightVizNode, source: query } as InsightVizNode,
                summaryContext
            )

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
                breakdownFilter: {
                    breakdown_type: 'person',
                    breakdown: 'some_prop',
                },
            }

            const result = summarizeInsight(
                { kind: NodeKind.InsightVizNode, source: query } as InsightVizNode,
                summaryContext
            )

            expect(result).toEqual("Pageview → random_event organization conversion rate by person's some_prop")
        })

        it('summarizes a user first-time Retention insight with the same event for cohortizing and returning', () => {
            const query: RetentionQuery = {
                kind: NodeKind.RetentionQuery,
                retentionFilter: {
                    targetEntity: {
                        id: '$autocapture',
                        name: '$autocapture',
                        type: 'events',
                    },
                    returningEntity: {
                        id: '$autocapture',
                        name: '$autocapture',
                        type: 'events',
                    },
                    retentionType: RETENTION_FIRST_OCCURRENCE_MATCHING_FILTERS,
                },
            }

            const result = summarizeInsight(
                { kind: NodeKind.InsightVizNode, source: query } as InsightVizNode,
                summaryContext
            )

            expect(result).toEqual(
                'Retention of users based on doing Autocapture first occurrence matching filters and returning with the same event'
            )
        })

        it('summarizes an organization recurring Retention insight with the different events for cohortizing and returning', () => {
            const query: RetentionQuery = {
                kind: NodeKind.RetentionQuery,
                retentionFilter: {
                    targetEntity: {
                        id: 'purchase',
                        name: 'purchase',
                        type: 'events',
                    },
                    returningEntity: {
                        id: '$pageview',
                        name: '$pageview',
                        type: 'events',
                    },
                    retentionType: RETENTION_RECURRING,
                },
                aggregation_group_type_index: 0,
            }

            const result = summarizeInsight(
                { kind: NodeKind.InsightVizNode, source: query } as InsightVizNode,
                summaryContext
            )

            expect(result).toEqual(
                'Retention of organizations based on doing purchase recurringly and returning with Pageview'
            )
        })

        it('summarizes a Paths insight based on all events', () => {
            const query: PathsQuery = {
                kind: NodeKind.PathsQuery,
                pathsFilter: {
                    includeEventTypes: [PathType.PageView, PathType.Screen, PathType.CustomEvent],
                },
            }

            const result = summarizeInsight(
                { kind: NodeKind.InsightVizNode, source: query } as InsightVizNode,
                summaryContext
            )

            expect(result).toEqual('User paths based on all events')
        })

        it('summarizes a Paths insight based on all events (empty includeEventTypes case)', () => {
            const query: PathsQuery = {
                kind: NodeKind.PathsQuery,
                pathsFilter: {
                    includeEventTypes: [],
                },
            }

            const result = summarizeInsight(
                { kind: NodeKind.InsightVizNode, source: query } as InsightVizNode,
                summaryContext
            )

            expect(result).toEqual('User paths based on all events')
        })

        it('summarizes a Paths insight based on pageviews with start and end points', () => {
            const query: PathsQuery = {
                kind: NodeKind.PathsQuery,
                pathsFilter: {
                    includeEventTypes: [PathType.PageView],
                    startPoint: '/landing-page',
                    endPoint: '/basket',
                },
            }

            const result = summarizeInsight(
                { kind: NodeKind.InsightVizNode, source: query } as InsightVizNode,
                summaryContext
            )

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

            const result = summarizeInsight(
                { kind: NodeKind.InsightVizNode, source: query } as InsightVizNode,
                summaryContext
            )

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

            const result = summarizeInsight(
                { kind: NodeKind.InsightVizNode, source: query } as InsightVizNode,
                summaryContext
            )

            expect(result).toEqual('User lifecycle based on Rageclick')
        })

        it('summarizes a Lifecycle insight with groups', () => {
            const query: LifecycleQuery = {
                kind: NodeKind.LifecycleQuery,
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        event: '$rageclick',
                        name: '$rageclick',
                    },
                ],
                aggregation_group_type_index: 0,
            }

            const result = summarizeInsight(
                { kind: NodeKind.InsightVizNode, source: query } as InsightVizNode,
                summaryContext
            )

            expect(result).toEqual('Organization lifecycle based on Rageclick')
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

            const result = summarizeInsight(query, summaryContext)

            expect(result).toEqual('event from events')
        })

        it('summarizes a two column events query', () => {
            const query: DataTableNode = {
                kind: NodeKind.DataTableNode,
                source: {
                    kind: NodeKind.EventsQuery,
                    select: ['event', 'timestamp'],
                },
            }

            const result = summarizeInsight(query, summaryContext)

            expect(result).toEqual('event, timestamp from events')
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

            const result = summarizeInsight(query, summaryContext)

            expect(result).toEqual('event from events')
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

            const result = summarizeInsight(query, summaryContext)

            expect(result).toEqual('timestamp from events')
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
            const result = summarizeInsight(query, summaryContext)

            expect(result).toEqual('count() from events')
        })

        it('avoids summarizing SQL query', () => {
            const query: DataTableNode = {
                kind: NodeKind.DataTableNode,
                full: true,
                source: {
                    kind: NodeKind.HogQLQuery,
                    query: 'select event,\n          person.properties.email from events\n  where timestamp > now() - interval 1 day',
                },
            }

            const result = summarizeInsight(query, summaryContext)

            expect(result).toEqual('SQL query')
        })

        it('summarizes a person query', () => {
            const query: DataTableNode = {
                kind: NodeKind.DataTableNode,
                columns: ['person', 'id', 'created_at', 'person.$delete'],
                source: {
                    kind: NodeKind.PersonsNode,
                },
            }
            const result = summarizeInsight(query, summaryContext)

            expect(result).toEqual('person, id, created_at, person.$delete from persons')
        })

        it('summarizes a Trends insight with multiple breakdowns', () => {
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
                breakdownFilter: {
                    breakdowns: [
                        {
                            type: 'event',
                            property: '$browser',
                        },
                        {
                            type: 'person',
                            property: 'custom_prop',
                        },
                        {
                            type: 'session',
                            property: '$session_duration',
                        },
                    ],
                },
            }

            const result = summarizeInsight(
                { kind: NodeKind.InsightVizNode, source: query } as InsightVizNode,
                summaryContext
            )

            expect(result).toEqual(
                "Pageview unique users by event's Browser, person's custom_prop, session's Session duration"
            )
        })
    })
})
