import posthog from 'posthog-js'
import { actions, connect, kea, key, listeners, path, props, selectors, reducers } from 'kea'
import { InsightLogicProps } from '~/types'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import {
    BreakdownFilter,
    DataNode,
    DateRange,
    InsightFilter,
    InsightQueryNode,
    InsightVizNode,
    Node,
    NodeKind,
} from '~/queries/schema'

import { insightLogic } from './insightLogic'
import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import {
    filterForQuery,
    filterPropertyForQuery,
    isFunnelsQuery,
    isInsightQueryNode,
    isInsightVizNode,
    isLifecycleQuery,
    isNodeWithSource,
    isPathsQuery,
    isRetentionQuery,
    isStickinessQuery,
    isTrendsQuery,
} from '~/queries/utils'
import { NON_TIME_SERIES_DISPLAY_TYPES } from 'lib/constants'
import { getBreakdown, getCompare, getDisplay, getInterval, getSeries } from '~/queries/nodes/InsightViz/utils'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { subscriptions } from 'kea-subscriptions'
import { displayTypesWithoutLegend } from 'lib/components/InsightLegend/utils'
import { insightDataLogic, queryFromKind } from 'scenes/insights/insightDataLogic'

const SHOW_TIMEOUT_MESSAGE_AFTER = 5000

import type { insightVizDataLogicType } from './insightVizDataLogicType'
import { sceneLogic } from 'scenes/sceneLogic'

export const insightVizDataLogic = kea<insightVizDataLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'insightVizDataLogic', key]),

    connect((props: InsightLogicProps) => ({
        values: [
            insightLogic,
            ['insight', 'isUsingDataExploration'],
            insightDataLogic,
            ['query'],
            // TODO: need to pass empty query here, as otherwise dataNodeLogic will throw
            dataNodeLogic({ key: insightVizDataNodeKey(props), query: {} as DataNode }),
            ['response as insightData', 'dataLoading as insightDataLoading', 'responseErrorObject as insightDataError'],
        ],
        actions: [
            insightLogic,
            ['setFilters', 'setInsight'],
            insightDataLogic,
            ['setQuery'],
            // TODO: need to pass empty query here, as otherwise dataNodeLogic will throw
            dataNodeLogic({ key: insightVizDataNodeKey(props), query: {} as DataNode }),
            ['loadData', 'loadDataSuccess', 'loadDataFailure'],
        ],
    })),

    actions({
        saveInsight: (redirectToViewMode = true) => ({ redirectToViewMode }),
        updateQuerySource: (querySource: Omit<Partial<InsightQueryNode>, 'kind'>) => ({ querySource }),
        updateInsightFilter: (insightFilter: InsightFilter) => ({ insightFilter }),
        updateDateRange: (dateRange: DateRange) => ({ dateRange }),
        updateBreakdown: (breakdown: BreakdownFilter) => ({ breakdown }),
        setTimedOutQueryId: (id: string | null) => ({ id }),
    }),

    reducers({
        timedOutQueryId: [
            null as null | string,
            {
                setTimedOutQueryId: (_, { id }) => id,
            },
        ],
    }),

    selectors({
        querySource: [
            (s) => [s.query],
            (query) => (isNodeWithSource(query) && isInsightQueryNode(query.source) ? query.source : null),
        ],

        isTrends: [(s) => [s.querySource], (q) => isTrendsQuery(q)],
        isFunnels: [(s) => [s.querySource], (q) => isFunnelsQuery(q)],
        isRetention: [(s) => [s.querySource], (q) => isRetentionQuery(q)],
        isPaths: [(s) => [s.querySource], (q) => isPathsQuery(q)],
        isStickiness: [(s) => [s.querySource], (q) => isStickinessQuery(q)],
        isLifecycle: [(s) => [s.querySource], (q) => isLifecycleQuery(q)],
        isTrendsLike: [(s) => [s.querySource], (q) => isTrendsQuery(q) || isLifecycleQuery(q) || isStickinessQuery(q)],
        supportsDisplay: [(s) => [s.querySource], (q) => isTrendsQuery(q) || isStickinessQuery(q)],
        supportsCompare: [(s) => [s.querySource], (q) => isTrendsQuery(q) || isStickinessQuery(q)],

        dateRange: [(s) => [s.querySource], (q) => (q ? q.dateRange : null)],
        breakdown: [(s) => [s.querySource], (q) => (q ? getBreakdown(q) : null)],
        display: [(s) => [s.querySource], (q) => (q ? getDisplay(q) : null)],
        compare: [(s) => [s.querySource], (q) => (q ? getCompare(q) : null)],
        series: [(s) => [s.querySource], (q) => (q ? getSeries(q) : null)],
        interval: [(s) => [s.querySource], (q) => (q ? getInterval(q) : null)],

        insightFilter: [(s) => [s.querySource], (q) => (q ? filterForQuery(q) : null)],
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

        hasLegend: [
            (s) => [s.isTrends, s.isStickiness, s.display],
            (isTrends, isStickiness, display) =>
                (isTrends || isStickiness) && !!display && !displayTypesWithoutLegend.includes(display),
        ],

        erroredQueryId: [
            (s) => [s.insightDataError],
            (insightDataError) => {
                return insightDataError?.queryId || null
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        updateDateRange: ({ dateRange }) => {
            const localQuerySource = values.querySource
                ? values.querySource
                : queryFromKind(NodeKind.TrendsQuery).source
            if (isInsightQueryNode(localQuerySource)) {
                const newQuerySource = { ...localQuerySource, dateRange }
                actions.updateQuerySource(newQuerySource)
            }
        },
        updateBreakdown: ({ breakdown }) => {
            const localQuerySource = values.querySource
                ? values.querySource
                : queryFromKind(NodeKind.TrendsQuery).source
            if (isInsightQueryNode(localQuerySource)) {
                const newQuerySource = { ...localQuerySource, breakdown }
                actions.updateQuerySource(newQuerySource)
            }
        },
        updateInsightFilter: ({ insightFilter }) => {
            const localQuerySource = values.querySource
                ? values.querySource
                : queryFromKind(NodeKind.TrendsQuery).source
            if (isInsightQueryNode(localQuerySource)) {
                const filterProperty = filterPropertyForQuery(localQuerySource)
                const newQuerySource = { ...localQuerySource }
                newQuerySource[filterProperty] = {
                    ...localQuerySource[filterProperty],
                    ...insightFilter,
                }
                actions.updateQuerySource(newQuerySource)
            }
        },
        updateQuerySource: ({ querySource }) => {
            const localQuery = values.query ? values.query : queryFromKind(NodeKind.TrendsQuery)
            if (localQuery && isInsightVizNode(localQuery)) {
                actions.setQuery({
                    ...localQuery,
                    source: { ...(localQuery as InsightVizNode).source, ...querySource },
                } as Node)
            }
        },
        setQuery: ({ query }) => {
            // safeguard against accidentally overwriting filters for non-flagged users
            if (!values.isUsingDataExploration) {
                return
            }

            if (isInsightVizNode(query)) {
                const querySource = query.source
                if (isLifecycleQuery(querySource)) {
                    const filters = queryNodeToFilter(querySource)
                    actions.setFilters(filters)
                }
            }
        },
        loadData: async ({ queryId }, breakpoint) => {
            actions.setTimedOutQueryId(null)

            await breakpoint(SHOW_TIMEOUT_MESSAGE_AFTER)

            if (!!values.insightDataLoading) {
                actions.setTimedOutQueryId(queryId)
                const tags = {
                    kind: values.querySource?.kind,
                    scene: sceneLogic.isMounted() ? sceneLogic.values.scene : null,
                }
                posthog.capture('insight timeout message shown', tags)
            }
        },
        loadDataSuccess: () => {
            actions.setTimedOutQueryId(null)
        },
        loadDataFailure: () => {
            actions.setTimedOutQueryId(null)
        },
    })),
    subscriptions(({ values, actions }) => ({
        /**
         * This subscription updates the insight for all visualizations
         * that haven't been refactored to use the data exploration yet.
         */
        insightData: (insightData: Record<string, any> | null) => {
            if (!values.isUsingDataExploration || insightData === null) {
                return
            }

            const updatedInsight = {
                ...values.insight,
                result: insightData?.result,
                next: insightData?.next,
            }
            if (values.querySource) {
                updatedInsight.filters = queryNodeToFilter(values.querySource)
            }
            actions.setInsight(updatedInsight, {})
        },
    })),
])
