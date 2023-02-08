import { kea, props, key, path, actions, reducers, selectors, connect, listeners } from 'kea'
import { FilterType, FunnelVizType, InsightLogicProps, InsightType, PathType, RetentionPeriod } from '~/types'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import {
    BreakdownFilter,
    DateRange,
    InsightFilter,
    InsightNodeKind,
    InsightQueryNode,
    InsightVizNode,
    Node,
    NodeKind,
} from '~/queries/schema'
import { BaseMathType } from '~/types'
import { ShownAsValue } from 'lib/constants'

import type { insightDataLogicType } from './insightDataLogicType'
import { insightLogic } from './insightLogic'
import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { filtersToQueryNode } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import {
    filterForQuery,
    filterPropertyForQuery,
    isTrendsQuery,
    isFunnelsQuery,
    isRetentionQuery,
    isPathsQuery,
    isStickinessQuery,
    isLifecycleQuery,
} from '~/queries/utils'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { cleanFilters } from './utils/cleanFilters'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { getBreakdown, getDisplay } from '~/queries/nodes/InsightViz/utils'

// TODO: should take the existing values.query and set params from previous view similar to
// cleanFilters({ ...values.filters, insight: type as InsightType }, values.filters)
const getCleanedQuery = (kind: InsightNodeKind): InsightVizNode => {
    if (kind === NodeKind.TrendsQuery) {
        return {
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.TrendsQuery,
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        name: '$pageview',
                        event: '$pageview',
                        math: BaseMathType.TotalCount,
                    },
                ],
                trendsFilter: {},
            },
        }
    } else if (kind === NodeKind.FunnelsQuery) {
        return {
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.FunnelsQuery,
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        name: '$pageview',
                        event: '$pageview',
                    },
                ],
                funnelsFilter: {
                    funnel_viz_type: FunnelVizType.Steps,
                },
            },
        }
    } else if (kind === NodeKind.RetentionQuery) {
        return {
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.RetentionQuery,
                retentionFilter: {
                    period: RetentionPeriod.Day,
                    total_intervals: 11,
                    target_entity: {
                        id: '$pageview',
                        name: '$pageview',
                        type: 'events',
                    },
                    returning_entity: {
                        id: '$pageview',
                        name: '$pageview',
                        type: 'events',
                    },
                    retention_type: 'retention_first_time',
                },
            },
        }
    } else if (kind === NodeKind.PathsQuery) {
        return {
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.PathsQuery,
                pathsFilter: {
                    include_event_types: [PathType.PageView],
                },
            },
        }
    } else if (kind === NodeKind.StickinessQuery) {
        return {
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.StickinessQuery,
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        name: '$pageview',
                        event: '$pageview',
                        math: BaseMathType.TotalCount,
                    },
                ],
                stickinessFilter: {},
            },
        }
    } else if (kind === NodeKind.LifecycleQuery) {
        return {
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.LifecycleQuery,
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        name: '$pageview',
                        event: '$pageview',
                        math: BaseMathType.TotalCount,
                    },
                ],
                lifecycleFilter: { shown_as: ShownAsValue.LIFECYCLE },
            },
        }
    } else {
        throw new Error('should not reach here')
    }
}

const getQueryFromFilters = (filters: Partial<FilterType>): InsightVizNode => {
    return {
        kind: NodeKind.InsightVizNode,
        source: filtersToQueryNode(filters),
    }
}

const getDefaultQuery = (insightProps: InsightLogicProps): InsightVizNode => ({
    kind: NodeKind.InsightVizNode,
    source: insightProps.cachedInsight?.filters
        ? filtersToQueryNode(insightProps.cachedInsight.filters)
        : { kind: NodeKind.TrendsQuery, series: [] },
})

export const insightDataLogic = kea<insightDataLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'insightDataLogic', key]),

    connect((props: InsightLogicProps) => ({
        values: [featureFlagLogic, ['featureFlags'], trendsLogic, ['toggledLifecycles as trendsLifecycles']],
        actions: [
            insightLogic,
            ['setFilters', 'setActiveView', 'setInsight', 'loadInsightSuccess', 'loadResultsSuccess'],
            trendsLogic(props),
            ['setLifecycles as setTrendsLifecycles'],
        ],
    })),

    actions({
        setQuery: (query: Node) => ({ query }),
        updateQuerySource: (query: Omit<Partial<InsightQueryNode>, 'kind'>) => ({ query }),
        updateInsightFilter: (insightFilter: InsightFilter) => ({ insightFilter }),
        updateDateRange: (dateRange: DateRange) => ({ dateRange }),
        updateBreakdown: (breakdown: BreakdownFilter) => ({ breakdown }),
    }),

    reducers(({ props }) => ({
        query: [
            getDefaultQuery(props) as Node,
            {
                setQuery: (_, { query }) => query,
            },
        ],
    })),

    selectors({
        isTrends: [(s) => [s.querySource], (q) => isTrendsQuery(q)],
        isFunnels: [(s) => [s.querySource], (q) => isFunnelsQuery(q)],
        isRetention: [(s) => [s.querySource], (q) => isRetentionQuery(q)],
        isPaths: [(s) => [s.querySource], (q) => isPathsQuery(q)],
        isStickiness: [(s) => [s.querySource], (q) => isStickinessQuery(q)],
        isLifecycle: [(s) => [s.querySource], (q) => isLifecycleQuery(q)],
        isTrendsLike: [(s) => [s.querySource], (q) => isTrendsQuery(q) || isLifecycleQuery(q) || isStickinessQuery(q)],
        supportsDisplay: [(s) => [s.querySource], (q) => isTrendsQuery(q) || isStickinessQuery(q)],

        querySource: [(s) => [s.query], (query) => (query as InsightVizNode).source],

        dateRange: [(s) => [s.querySource], (q) => q.dateRange],
        breakdown: [(s) => [s.querySource], (q) => getBreakdown(q)],
        display: [(s) => [s.querySource], (q) => getDisplay(q)],

        insightFilter: [(s) => [s.querySource], (q) => filterForQuery(q)],
        trendsFilter: [(s) => [s.querySource], (q) => (isTrendsQuery(q) ? q.trendsFilter : null)],
        funnelsFilter: [(s) => [s.querySource], (q) => (isFunnelsQuery(q) ? q.funnelsFilter : null)],
        retentionFilter: [(s) => [s.querySource], (q) => (isRetentionQuery(q) ? q.retentionFilter : null)],
        pathsFilter: [(s) => [s.querySource], (q) => (isPathsQuery(q) ? q.pathsFilter : null)],
        stickinessFilter: [(s) => [s.querySource], (q) => (isStickinessQuery(q) ? q.stickinessFilter : null)],
        lifecycleFilter: [(s) => [s.querySource], (q) => (isLifecycleQuery(q) ? q.lifecycleFilter : null)],
    }),

    listeners(({ actions, values }) => ({
        updateDateRange: ({ dateRange }) => {
            const newQuerySource = { ...values.querySource, dateRange }
            actions.updateQuerySource(newQuerySource)
        },
        updateBreakdown: ({ breakdown }) => {
            const newQuerySource = { ...values.querySource, breakdown }
            actions.updateQuerySource(newQuerySource)
        },
        updateInsightFilter: ({ insightFilter }) => {
            const filterProperty = filterPropertyForQuery(values.querySource)
            const newQuerySource = { ...values.querySource }
            newQuerySource[filterProperty] = {
                ...values.querySource[filterProperty],
                ...insightFilter,
            }
            actions.updateQuerySource(newQuerySource)
        },
        updateQuerySource: ({ query }) => {
            actions.setQuery({
                ...values.query,
                source: { ...(values.query as InsightVizNode).source, ...query },
            } as Node)
        },
        setQuery: ({ query }) => {
            // safeguard against accidentally overwriting filters for non-flagged users
            if (!values.featureFlags[FEATURE_FLAGS.DATA_EXPLORATION_INSIGHTS]) {
                return
            }

            const querySource = (query as InsightVizNode).source
            if (isLifecycleQuery(querySource)) {
                const filters = queryNodeToFilter(querySource)
                actions.setFilters(filters)

                if (querySource.lifecycleFilter?.toggledLifecycles !== values.trendsLifecycles) {
                    actions.setTrendsLifecycles(
                        querySource.lifecycleFilter?.toggledLifecycles
                            ? querySource.lifecycleFilter.toggledLifecycles
                            : ['new', 'resurrecting', 'returning', 'dormant']
                    )
                }
            }
        },
        setActiveView: ({ type }) => {
            if (type === InsightType.TRENDS) {
                actions.setQuery(getCleanedQuery(NodeKind.TrendsQuery))
            } else if (type === InsightType.FUNNELS) {
                actions.setQuery(getCleanedQuery(NodeKind.FunnelsQuery))
            } else if (type === InsightType.RETENTION) {
                actions.setQuery(getCleanedQuery(NodeKind.RetentionQuery))
            } else if (type === InsightType.PATHS) {
                actions.setQuery(getCleanedQuery(NodeKind.PathsQuery))
            } else if (type === InsightType.STICKINESS) {
                actions.setQuery(getCleanedQuery(NodeKind.StickinessQuery))
            } else if (type === InsightType.LIFECYCLE) {
                actions.setQuery(getCleanedQuery(NodeKind.LifecycleQuery))
            }
        },
        setInsight: ({ insight: { filters }, options: { overrideFilter } }) => {
            if (overrideFilter) {
                actions.setQuery(getQueryFromFilters(cleanFilters(filters || {})))
            }
        },
        loadInsightSuccess: ({ insight }) => {
            if (!!insight.query) {
                actions.setQuery(insight.query)
            } else if (!!insight.filters && !!Object.keys(insight.filters).length) {
                const query = getQueryFromFilters(insight.filters)
                actions.setQuery(query)
            }
        },
        loadResultsSuccess: ({ insight }) => {
            if (!!insight.query) {
                actions.setQuery(insight.query)
            } else if (!!insight.filters && !!Object.keys(insight.filters).length) {
                const query = getQueryFromFilters(insight.filters)
                actions.setQuery(query)
            }
        },
    })),
])
