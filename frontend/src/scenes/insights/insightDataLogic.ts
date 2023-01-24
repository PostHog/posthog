import { kea, props, key, path, actions, reducers, selectors, connect, listeners } from 'kea'
import { FilterType, InsightLogicProps, InsightType, PathType } from '~/types'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { BreakdownFilter, InsightFilter, InsightQueryNode, InsightVizNode, Node, NodeKind } from '~/queries/schema'
import { BaseMathType } from '~/types'
import { ShownAsValue } from 'lib/constants'

import type { insightDataLogicType } from './insightDataLogicType'
import { insightLogic } from './insightLogic'
import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { filtersToQueryNode } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { filterForQuery, filterPropertyForQuery, isLifecycleQuery, isUnimplementedQuery } from '~/queries/utils'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { cleanFilters } from './utils/cleanFilters'
import { trendsLogic } from 'scenes/trends/trendsLogic'

// TODO: should take the existing values.query and set params from previous view similar to
// cleanFilters({ ...values.filters, insight: type as InsightType }, values.filters)
const getCleanedQuery = (
    kind:
        | NodeKind.TrendsQuery
        | NodeKind.FunnelsQuery
        | NodeKind.PathsQuery
        | NodeKind.StickinessQuery
        | NodeKind.LifecycleQuery
        | NodeKind.UnimplementedQuery
): InsightVizNode => {
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
                funnelsFilter: {},
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
        return {
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.UnimplementedQuery,
            },
        }
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
        querySource: [(s) => [s.query], (query) => (query as InsightVizNode).source],
        insightFilter: [(s) => [s.querySource], (querySource) => filterForQuery(querySource)],
    }),

    listeners(({ actions, values }) => ({
        updateBreakdown: ({ breakdown }) => {
            const newQuerySource = { ...values.querySource, breakdown }
            actions.updateQuerySource(newQuerySource)
        },
        updateInsightFilter: ({ insightFilter }) => {
            if (isUnimplementedQuery(values.querySource)) {
                return
            }

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
            } else if (type === InsightType.PATHS) {
                actions.setQuery(getCleanedQuery(NodeKind.PathsQuery))
            } else if (type === InsightType.STICKINESS) {
                actions.setQuery(getCleanedQuery(NodeKind.StickinessQuery))
            } else if (type === InsightType.LIFECYCLE) {
                actions.setQuery(getCleanedQuery(NodeKind.LifecycleQuery))
            } else {
                actions.setQuery(getCleanedQuery(NodeKind.UnimplementedQuery))
            }
        },
        setInsight: ({ insight: { filters }, options: { overrideFilter } }) => {
            if (overrideFilter) {
                actions.setQuery(getQueryFromFilters(cleanFilters(filters || {})))
            }
        },
        loadInsightSuccess: ({ insight }) => {
            if (insight.filters) {
                const query = getQueryFromFilters(insight.filters)
                actions.setQuery(query)
            }
        },
        loadResultsSuccess: ({ insight }) => {
            if (insight.filters) {
                const query = getQueryFromFilters(insight.filters)
                actions.setQuery(query)
            }
        },
    })),
])
