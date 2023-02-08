import { kea, props, key, path, actions, reducers, selectors, connect, listeners } from 'kea'
import { FilterType, InsightLogicProps, InsightType } from '~/types'
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
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { getBreakdown, getDisplay } from '~/queries/nodes/InsightViz/utils'
import { nodeKindToDefaultQuery } from '~/queries/nodes/InsightQuery/defaults'

const getDefaultQuery = (insightProps: InsightLogicProps): InsightVizNode => {
    const filters = insightProps.cachedInsight?.filters
    return filters ? queryFromFilters(filters) : queryFromKind(NodeKind.TrendsQuery)
}

const queryFromFilters = (filters: Partial<FilterType>): InsightVizNode => ({
    kind: NodeKind.InsightVizNode,
    source: filtersToQueryNode(filters),
})

const queryFromKind = (kind: InsightNodeKind): InsightVizNode => ({
    kind: NodeKind.InsightVizNode,
    source: nodeKindToDefaultQuery[kind],
})

export const insightDataLogic = kea<insightDataLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'insightDataLogic', key]),

    connect((props: InsightLogicProps) => ({
        values: [featureFlagLogic, ['featureFlags'], trendsLogic, ['toggledLifecycles as trendsLifecycles']],
        actions: [
            insightLogic,
            ['setFilters', 'setInsight', 'loadInsightSuccess', 'loadResultsSuccess'],
            trendsLogic(props),
            ['setLifecycles as setTrendsLifecycles'],
        ],
    })),

    actions({
        setQuery: (query: Node) => ({ query }),
        setActiveView: (activeView: InsightType) => ({ activeView }),
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
                setActiveView: (_, { activeView }): InsightVizNode => {
                    if (activeView === InsightType.TRENDS) {
                        return queryFromKind(NodeKind.TrendsQuery)
                    } else if (activeView === InsightType.FUNNELS) {
                        return queryFromKind(NodeKind.FunnelsQuery)
                    } else if (activeView === InsightType.RETENTION) {
                        return queryFromKind(NodeKind.RetentionQuery)
                    } else if (activeView === InsightType.PATHS) {
                        return queryFromKind(NodeKind.PathsQuery)
                    } else if (activeView === InsightType.STICKINESS) {
                        return queryFromKind(NodeKind.StickinessQuery)
                    } else if (activeView === InsightType.LIFECYCLE) {
                        return queryFromKind(NodeKind.LifecycleQuery)
                    } else {
                        throw new Error('unsupported insight type')
                    }
                },
            },
        ],
        activeView: [
            InsightType.TRENDS as InsightType,
            {
                setActiveView: (_, { activeView }) => activeView,
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
    })),
])
