import { kea, props, key, path, actions, reducers, selectors, connect, listeners } from 'kea'
import { FilterType, InsightLogicProps } from '~/types'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import {
    BreakdownFilter,
    DataNode,
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
    isInsightVizNode,
} from '~/queries/utils'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS, NON_TIME_SERIES_DISPLAY_TYPES } from 'lib/constants'
import { cleanFilters } from './utils/cleanFilters'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { getBreakdown, getDisplay, getCompare, getSeries, getInterval } from '~/queries/nodes/InsightViz/utils'
import { nodeKindToDefaultQuery } from '~/queries/nodes/InsightQuery/defaults'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { subscriptions } from 'kea-subscriptions'
import { queryExportContext } from '~/queries/query'

const defaultQuery = (insightProps: InsightLogicProps): InsightVizNode => {
    const filters = insightProps.cachedInsight?.filters
    return filters ? queryFromFilters(filters) : queryFromKind(NodeKind.TrendsQuery)
}

const queryFromFilters = (filters: Partial<FilterType>): InsightVizNode => ({
    kind: NodeKind.InsightVizNode,
    source: filtersToQueryNode(filters),
})

export const queryFromKind = (kind: InsightNodeKind): InsightVizNode => ({
    kind: NodeKind.InsightVizNode,
    source: nodeKindToDefaultQuery[kind],
})

export const insightDataLogic = kea<insightDataLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'insightDataLogic', key]),

    connect((props: InsightLogicProps) => ({
        values: [
            insightLogic,
            ['insight', 'isUsingDataExploration'],
            featureFlagLogic,
            ['featureFlags'],
            trendsLogic,
            ['toggledLifecycles as trendsLifecycles'],
            // TODO: need to pass empty query here, as otherwise dataNodeLogic will throw
            dataNodeLogic({ key: insightVizDataNodeKey(props), query: {} as DataNode }),
            ['response'],
        ],
        actions: [
            insightLogic,
            [
                'setFilters',
                'setInsight',
                'loadInsightSuccess',
                'loadResultsSuccess',
                'saveInsight as insightLogicSaveInsight',
            ],
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
        saveInsight: (redirectToViewMode = true) => ({ redirectToViewMode }),
    }),

    reducers(({ props }) => ({
        query: [
            defaultQuery(props) as Node,
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
        supportsCompare: [(s) => [s.querySource], (q) => isTrendsQuery(q) || isStickinessQuery(q)],

        querySource: [(s) => [s.query], (query) => (query as InsightVizNode).source],

        dateRange: [(s) => [s.querySource], (q) => q.dateRange],
        breakdown: [(s) => [s.querySource], (q) => getBreakdown(q)],
        display: [(s) => [s.querySource], (q) => getDisplay(q)],
        compare: [(s) => [s.querySource], (q) => getCompare(q)],
        series: [(s) => [s.querySource], (q) => getSeries(q)],
        interval: [(s) => [s.querySource], (q) => getInterval(q)],

        insightFilter: [(s) => [s.querySource], (q) => filterForQuery(q)],
        trendsFilter: [(s) => [s.querySource], (q) => (isTrendsQuery(q) ? q.trendsFilter : null)],
        funnelsFilter: [(s) => [s.querySource], (q) => (isFunnelsQuery(q) ? q.funnelsFilter : null)],
        retentionFilter: [(s) => [s.querySource], (q) => (isRetentionQuery(q) ? q.retentionFilter : null)],
        pathsFilter: [(s) => [s.querySource], (q) => (isPathsQuery(q) ? q.pathsFilter : null)],
        stickinessFilter: [(s) => [s.querySource], (q) => (isStickinessQuery(q) ? q.stickinessFilter : null)],
        lifecycleFilter: [(s) => [s.querySource], (q) => (isLifecycleQuery(q) ? q.lifecycleFilter : null)],

        isNonTimeSeriesDisplay: [
            (s) => [s.display],
            (display) => !!display && NON_TIME_SERIES_DISPLAY_TYPES.includes(display),
        ],

        isQueryBasedInsight: [
            (s) => [s.query],
            (query) => {
                return !isInsightVizNode(query) && !!query
            },
        ],

        exportContext: [
            (s) => [s.query, s.insight],
            (query, insight) => {
                const filename = ['export', insight.name || insight.derived_name].join('-')
                return { ...queryExportContext(query), filename }
            },
        ],
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
        setInsight: ({ insight: { filters }, options: { overrideFilter } }) => {
            if (overrideFilter) {
                actions.setQuery(queryFromFilters(cleanFilters(filters || {})))
            }
        },
        loadInsightSuccess: ({ insight }) => {
            if (!!insight.query) {
                actions.setQuery(insight.query)
            } else if (!!insight.filters && !!Object.keys(insight.filters).length) {
                const query = queryFromFilters(insight.filters)
                actions.setQuery(query)
            }
        },
        loadResultsSuccess: ({ insight }) => {
            if (!!insight.query) {
                actions.setQuery(insight.query)
            } else if (!!insight.filters && !!Object.keys(insight.filters).length) {
                const query = queryFromFilters(insight.filters)
                actions.setQuery(query)
            }
        },
        saveInsight: ({ redirectToViewMode }) => {
            actions.setInsight(
                {
                    ...values.insight,
                    ...(values.isQueryBasedInsight ? { query: values.query, filters: {} } : {}),
                },
                { overrideFilter: true, fromPersistentApi: false }
            )
            actions.insightLogicSaveInsight(redirectToViewMode)
        },
    })),
    subscriptions(({ values, actions }) => ({
        /**
         * This subscription updates the insight for all visualizations
         * that haven't been refactored to use the data exploration yet.
         */
        response: (response: Record<string, any> | null) => {
            if (!values.isUsingDataExploration) {
                return
            }

            actions.setInsight(
                {
                    ...values.insight,
                    result: response?.result,
                    next: response?.next,
                    // filters: queryNodeToFilter(query.source),
                },
                {}
            )
        },
    })),
])
