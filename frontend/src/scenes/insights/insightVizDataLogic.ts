import posthog from 'posthog-js'
import { actions, connect, kea, key, listeners, path, props, selectors, reducers } from 'kea'
import { ChartDisplayType, InsightLogicProps } from '~/types'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import {
    BreakdownFilter,
    DateRange,
    InsightFilter,
    InsightQueryNode,
    InsightVizNode,
    Node,
    NodeKind,
    TrendsQuery,
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
import { NON_TIME_SERIES_DISPLAY_TYPES, PERCENT_STACK_VIEW_DISPLAY_TYPE } from 'lib/constants'
import {
    getBreakdown,
    getCompare,
    getDisplay,
    getFormula,
    getInterval,
    getSeries,
    getShownAs,
    getShowPercentStackView,
    getShowValueOnSeries,
} from '~/queries/nodes/InsightViz/utils'
import { DISPLAY_TYPES_WITHOUT_LEGEND } from 'lib/components/InsightLegend/utils'
import { insightDataLogic, queryFromKind } from 'scenes/insights/insightDataLogic'

import { sceneLogic } from 'scenes/sceneLogic'

import type { insightVizDataLogicType } from './insightVizDataLogicType'
import { parseProperties } from 'lib/components/PropertyFilters/utils'
import { filterTestAccountsDefaultsLogic } from 'scenes/project/Settings/filterTestAccountDefaultsLogic'

const SHOW_TIMEOUT_MESSAGE_AFTER = 5000

export const insightVizDataLogic = kea<insightVizDataLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'insightVizDataLogic', key]),

    connect(() => ({
        values: [
            insightDataLogic,
            ['query', 'insightQuery', 'insightData', 'insightDataLoading', 'insightDataError'],
            filterTestAccountsDefaultsLogic,
            ['filterTestAccountsDefault'],
        ],
        actions: [
            insightLogic,
            ['setFilters'],
            insightDataLogic,
            ['setQuery', 'setInsightData', 'loadData', 'loadDataSuccess', 'loadDataFailure'],
        ],
    })),

    actions({
        saveInsight: (redirectToViewMode = true) => ({ redirectToViewMode }),
        updateQuerySource: (querySource: Omit<Partial<InsightQueryNode>, 'kind'>) => ({ querySource }),
        updateInsightFilter: (insightFilter: InsightFilter) => ({ insightFilter }),
        updateDateRange: (dateRange: DateRange) => ({ dateRange }),
        updateBreakdown: (breakdown: BreakdownFilter) => ({ breakdown }),
        updateDisplay: (display: ChartDisplayType | undefined) => ({ display }),
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
        supportsPercentStackView: [
            (s) => [s.querySource, s.display],
            (q, display) =>
                isTrendsQuery(q) &&
                PERCENT_STACK_VIEW_DISPLAY_TYPE.includes(display || ChartDisplayType.ActionsLineGraph),
        ],

        dateRange: [(s) => [s.querySource], (q) => (q ? q.dateRange : null)],
        breakdown: [(s) => [s.querySource], (q) => (q ? getBreakdown(q) : null)],
        display: [(s) => [s.querySource], (q) => (q ? getDisplay(q) : null)],
        compare: [(s) => [s.querySource], (q) => (q ? getCompare(q) : null)],
        formula: [(s) => [s.querySource], (q) => (q ? getFormula(q) : null)],
        series: [(s) => [s.querySource], (q) => (q ? getSeries(q) : null)],
        interval: [(s) => [s.querySource], (q) => (q ? getInterval(q) : null)],
        properties: [(s) => [s.querySource], (q) => (q ? q.properties : null)],
        samplingFactor: [(s) => [s.querySource], (q) => (q ? q.samplingFactor : null)],
        shownAs: [(s) => [s.querySource], (q) => (q ? getShownAs(q) : null)],
        showValueOnSeries: [(s) => [s.querySource], (q) => (q ? getShowValueOnSeries(q) : null)],
        showPercentStackView: [(s) => [s.querySource], (q) => (q ? getShowPercentStackView(q) : null)],

        insightFilter: [(s) => [s.querySource], (q) => (q ? filterForQuery(q) : null)],
        trendsFilter: [(s) => [s.querySource], (q) => (isTrendsQuery(q) ? q.trendsFilter : null)],
        funnelsFilter: [(s) => [s.querySource], (q) => (isFunnelsQuery(q) ? q.funnelsFilter : null)],
        retentionFilter: [(s) => [s.querySource], (q) => (isRetentionQuery(q) ? q.retentionFilter : null)],
        pathsFilter: [(s) => [s.querySource], (q) => (isPathsQuery(q) ? q.pathsFilter : null)],
        stickinessFilter: [(s) => [s.querySource], (q) => (isStickinessQuery(q) ? q.stickinessFilter : null)],
        lifecycleFilter: [(s) => [s.querySource], (q) => (isLifecycleQuery(q) ? q.lifecycleFilter : null)],

        isUsingSessionAnalysis: [
            (s) => [s.series, s.breakdown, s.properties],
            (series, breakdown, properties) => {
                const using_session_breakdown = breakdown?.breakdown_type === 'session'
                const using_session_math = series?.some((entity) => entity.math === 'unique_session')
                const using_session_property_math = series?.some((entity) => {
                    // Should be made more generic is we ever add more session properties
                    return entity.math_property === '$session_duration'
                })
                const using_entity_session_property_filter = series?.some((entity) => {
                    return parseProperties(entity.properties).some((property) => property.type === 'session')
                })
                const using_global_session_property_filter = parseProperties(properties).some(
                    (property) => property.type === 'session'
                )
                return (
                    using_session_breakdown ||
                    using_session_math ||
                    using_session_property_math ||
                    using_entity_session_property_filter ||
                    using_global_session_property_filter
                )
            },
        ],

        isNonTimeSeriesDisplay: [
            (s) => [s.display],
            (display) => !!display && NON_TIME_SERIES_DISPLAY_TYPES.includes(display),
        ],

        isSingleSeries: [
            (s) => [s.isTrends, s.formula, s.series, s.breakdown],
            (isTrends, formula, series, breakdown): boolean => {
                return ((isTrends && !!formula) || (series || []).length <= 1) && !breakdown?.breakdown
            },
        ],

        hasLegend: [
            (s) => [s.isTrends, s.isStickiness, s.display],
            (isTrends, isStickiness, display) =>
                (isTrends || isStickiness) && !!display && !DISPLAY_TYPES_WITHOUT_LEGEND.includes(display),
        ],

        hasFormula: [(s) => [s.formula], (formula) => formula !== undefined],

        erroredQueryId: [
            (s) => [s.insightDataError],
            (insightDataError) => {
                return insightDataError?.queryId || null
            },
        ],

        timezone: [(s) => [s.insightData], (insightData) => insightData?.timezone || 'UTC'],
    }),

    listeners(({ actions, values }) => ({
        updateDateRange: ({ dateRange }) => {
            const localQuerySource = values.querySource
                ? values.querySource
                : queryFromKind(NodeKind.TrendsQuery, values.filterTestAccountsDefault).source
            if (isInsightQueryNode(localQuerySource)) {
                const newQuerySource = { ...localQuerySource, dateRange }
                actions.updateQuerySource(newQuerySource)
            }
        },
        updateBreakdown: ({ breakdown }) => {
            const localQuerySource = values.querySource
                ? values.querySource
                : queryFromKind(NodeKind.TrendsQuery, values.filterTestAccountsDefault).source
            if (isInsightQueryNode(localQuerySource)) {
                const newQuerySource = {
                    ...localQuerySource,
                    breakdown: { ...(localQuerySource as TrendsQuery).breakdown, ...breakdown },
                }
                actions.updateQuerySource(newQuerySource)
            }
        },
        updateDisplay: ({ display }) => {
            actions.updateInsightFilter({ display })
        },
        updateInsightFilter: ({ insightFilter }) => {
            const localQuerySource = values.querySource
                ? values.querySource
                : queryFromKind(NodeKind.TrendsQuery, values.filterTestAccountsDefault).source
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
            const localQuery = values.query
                ? values.query
                : queryFromKind(NodeKind.TrendsQuery, values.filterTestAccountsDefault)
            if (localQuery && isInsightVizNode(localQuery)) {
                actions.setQuery({
                    ...localQuery,
                    source: { ...(localQuery as InsightVizNode).source, ...querySource },
                } as Node)
            }
        },
        setQuery: ({ query }) => {
            if (isInsightVizNode(query)) {
                const querySource = query.source
                const filters = queryNodeToFilter(querySource)
                actions.setFilters(filters)
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
])
