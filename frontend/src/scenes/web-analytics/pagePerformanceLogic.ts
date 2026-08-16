import {
    MakeLogicType,
    actions,
    afterMount,
    connect,
    isBreakpoint,
    kea,
    listeners,
    path,
    reducers,
    selectors,
} from 'kea'
import { subscriptions } from 'kea-subscriptions'

import { dayjs } from 'lib/dayjs'
import { componentsToDayJs, dateStringToComponents, dateStringToDayJs } from 'lib/utils/dateFilters'
import { isAbortedRequest } from 'lib/utils/requests'
import { teamLogic } from 'scenes/teamLogic'

import { actionsModel } from '~/models/actionsModel'
import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { OverviewItem } from '~/queries/nodes/OverviewGrid/OverviewGrid'
import { performQuery } from '~/queries/query'
import {
    ActionConversionGoal,
    CompareFilter,
    CustomEventConversionGoal,
    DataTableNode,
    EventsNode,
    GroupNode,
    HogQLQuery,
    InsightVizNode,
    NodeKind,
    TrendsFilter,
    WebAnalyticsConversionGoal,
    WebAnalyticsOrderByFields,
    WebAnalyticsPropertyFilters,
    WebBotsBreakdown,
    WebStatsBreakdown,
    WebStatsTableQuery,
} from '~/queries/schema/schema-general'
import { escapeDottedHogQLIdentifier, escapeHogQLString } from '~/queries/utils'
import {
    ActionType,
    BaseMathType,
    ChartDisplayType,
    FilterLogicalOperator,
    InsightLogicProps,
    PropertyFilterType,
    PropertyOperator,
    TeamType,
} from '~/types'

import type { TeamPublicType } from '../../types'
import {
    BOT_ANALYTICS_EVENTS,
    TileId,
    WEB_ANALYTICS_DATA_COLLECTION_NODE_ID,
    WEB_ANALYTICS_DEFAULT_QUERY_TAGS,
    getWebAnalyticsBreakdownFilter,
    loadPriorityMap,
} from './common'
import { getDashboardItemId } from './insightsUtils'
import { webAnalyticsLogic } from './webAnalyticsLogic'
import type { DateFilterState } from './webAnalyticsLogic'

const PAGE_PERFORMANCE_EVENTS = "('$pageview', '$screen', '$http_log')"

const HUMAN_EVENTS = "('$pageview', '$screen')"

const PAGE_TABLE_LIMIT = 20

const PAGE_CANDIDATE_LIMIT = 200

const HUMAN_VIEW = "(event = '$pageview' OR event = '$screen') AND NOT `$virt_is_bot`"

const GOOGLE_VIEW = `${HUMAN_VIEW} AND session.$channel_type = 'Organic Search' AND session.$entry_referring_domain ILIKE '%google%'`

const AI_VIEW = `${HUMAN_VIEW} AND session.$channel_type = 'AI'`

const CRAWLER =
    "`$virt_is_bot` = true AND `$virt_bot_name` != '' AND `$virt_traffic_category` IN ('ai_crawler', 'ai_assistant', 'ai_search')"

export type PagePerformanceMetric = 'llm_referrals' | 'agent_crawls' | 'google_search'

export interface PagePerformanceBreakdownState {
    page: string
    metric: PagePerformanceMetric
}

export interface PagePerformanceOrderBy {
    column: string
    direction: 'ASC' | 'DESC'
}

export interface PagePerformanceWindow {
    currentFrom: dayjs.Dayjs | null
    currentTo: dayjs.Dayjs
    previousFrom: dayjs.Dayjs | null
    previousTo: dayjs.Dayjs | null
    timezone: string
}

export interface OverviewTotals {
    visitors: number
    visitorsPrevious: number
    google: number
    googlePrevious: number
    llm: number
    llmPrevious: number
    crawls: number
    crawlsPrevious: number
    pages: number
}

export interface AiSectionQueries {
    referralTrend: InsightVizNode
    byEngine: DataTableNode
    landingPages: DataTableNode
    crawlerTrend: InsightVizNode
    byCrawler: DataTableNode
    crawledPages: DataTableNode
}

export const OVERVIEW_CARD_LABELS: Record<string, string> = {
    visitors: 'Visitors',
    google_search: 'Google search',
    llm_referrals: 'LLM referrals',
    agent_crawls: 'Agent crawls',
}

const tsLiteral = (date: dayjs.Dayjs, timezone: string): string => date.tz(timezone).format("'YYYY-MM-DD HH:mm:ss'")

const conversionMatch = (conversionGoal: WebAnalyticsConversionGoal | null): string | null => {
    if (conversionGoal && 'actionId' in conversionGoal) {
        return `matchesAction(${(conversionGoal as ActionConversionGoal).actionId})`
    }
    if (conversionGoal && 'customEventName' in conversionGoal) {
        return `event = ${escapeHogQLString((conversionGoal as CustomEventConversionGoal).customEventName)}`
    }
    return null
}

const RAW_PATH = 'properties.$pathname'

export const buildPagePerformancePathExpr = (
    source: string,
    enabled: boolean,
    filters: { regex?: string; alias?: string }[] | undefined
): string => {
    if (!enabled || !filters?.length) {
        return source
    }
    let expr = source
    for (const f of filters) {
        if (f.regex && f.alias != null) {
            expr = `replaceRegexpAll(${expr}, ${escapeHogQLString(f.regex)}, ${escapeHogQLString(f.alias)})`
        }
    }
    return expr
}

export const resolvePagePerformanceWindow = (
    dateFilter: DateFilterState,
    compareFilter: CompareFilter,
    timezone: string,
    now: dayjs.Dayjs = dayjs().tz(timezone)
): PagePerformanceWindow => {
    const currentFrom =
        dateFilter.dateFrom === 'all'
            ? null
            : (dateStringToDayJs(dateFilter.dateFrom, timezone) ?? now.subtract(7, 'day'))
    const parsedCurrentTo = dateFilter.dateTo ? dateStringToDayJs(dateFilter.dateTo, timezone) : null
    const currentTo =
        parsedCurrentTo && /^\d{4}-\d{2}-\d{2}$/.test(dateFilter.dateTo ?? '')
            ? parsedCurrentTo.endOf('day')
            : (parsedCurrentTo ?? now)

    if (!compareFilter.compare || !currentFrom) {
        return { currentFrom, currentTo, previousFrom: null, previousTo: null, timezone }
    }

    const spanMs = Math.max(currentTo.diff(currentFrom), 1)
    const compareToComponents = dateStringToComponents(compareFilter.compare_to ?? null)
    const previousFrom = compareToComponents
        ? componentsToDayJs(compareToComponents, currentFrom, timezone)
        : currentFrom.subtract(spanMs, 'millisecond')
    const previousTo = compareToComponents ? previousFrom.add(spanMs, 'millisecond') : currentFrom

    return { currentFrom, currentTo, previousFrom, previousTo, timezone }
}

const SORTABLE_COLUMNS = new Set([
    'breakdown_value',
    'visitors',
    'google_search',
    'llm_referrals',
    'agent_crawls',
    'conversions',
    'avg_time',
])
const orderByExpr = (column: string): string =>
    `"context.columns.${SORTABLE_COLUMNS.has(column) ? column : 'visitors'}"`

const windowPredicates = (window: PagePerformanceWindow): { cur: string; prev: string; full: string } => {
    const upperBound = `timestamp <= ${tsLiteral(window.currentTo, window.timezone)}`
    const cur = window.currentFrom
        ? `timestamp >= ${tsLiteral(window.currentFrom, window.timezone)} AND ${upperBound}`
        : upperBound
    const prev =
        window.previousFrom && window.previousTo
            ? `timestamp >= ${tsLiteral(window.previousFrom, window.timezone)} AND timestamp < ${tsLiteral(window.previousTo, window.timezone)}`
            : 'false'
    return { cur, prev, full: `(${cur}) OR (${prev})` }
}

const pageKeyExpr = (pathExpr: string): string => `concat(coalesce(properties.$host, ''), ${pathExpr})`

const pageCandidatesPredicate = (pageKey: string, candidates: string[]): string =>
    candidates.length > 0 ? `${pageKey} IN (${candidates.map(escapeHogQLString).join(', ')})` : 'false'

export const buildPagePerformanceTableQuery = (
    window: PagePerformanceWindow,
    orderBy: PagePerformanceOrderBy,
    conversionGoal: WebAnalyticsConversionGoal | null,
    pathExpr: string,
    previousPathExpr: string,
    candidates: string[]
): string => {
    const { cur, prev, full } = windowPredicates(window)
    const pageKey = pageKeyExpr(pathExpr)
    const previousPageKey = pageKeyExpr(previousPathExpr)
    const candidatePredicate = pageCandidatesPredicate(pageKeyExpr(RAW_PATH), candidates)
    const previousCandidatePredicate = pageCandidatesPredicate(
        pageKeyExpr('properties.$prev_pageview_pathname'),
        candidates
    )

    const match = conversionMatch(conversionGoal)
    const conversions = match
        ? `tuple(countIf((${match}) AND ${cur}), uniqIf(person_id, (${HUMAN_VIEW}) AND ${cur}))`
        : 'tuple(0, 0)'

    const orderExpr = orderByExpr(orderBy.column)

    return `
SELECT
    ${pageKey} AS "context.columns.breakdown_value",
    tuple(
        uniqIf(person_id, (${HUMAN_VIEW}) AND ${cur}),
        uniqIf(person_id, (${HUMAN_VIEW}) AND ${prev})
    ) AS "context.columns.visitors",
    tuple(
        uniqIf(person_id, (${GOOGLE_VIEW}) AND ${cur}),
        uniqIf(person_id, (${HUMAN_VIEW}) AND ${cur})
    ) AS "context.columns.google_search",
    tuple(
        uniqIf(person_id, (${AI_VIEW}) AND ${cur}),
        uniqIf(person_id, (${AI_VIEW}) AND ${prev})
    ) AS "context.columns.llm_referrals",
    tuple(
        countIf((${CRAWLER}) AND ${cur}),
        uniqIf(\`$virt_bot_name\`, (${CRAWLER}) AND ${cur})
    ) AS "context.columns.agent_crawls",
    ${conversions} AS "context.columns.conversions",
    any(page_durations.avg_time) AS "context.columns.avg_time"
FROM events
LEFT JOIN (
    SELECT
        ${previousPageKey} AS page_key,
        quantile(0.90)(least(toFloat(properties.$prev_pageview_duration), 86400)) AS avg_time
    FROM events
    WHERE and(
        event IN ('$pageview', '$screen', '$pageleave'),
        properties.$prev_pageview_pathname IS NOT NULL,
        properties.$prev_pageview_duration IS NOT NULL,
        (${previousCandidatePredicate}),
        (${cur}),
        {filters}
    )
    GROUP BY page_key
) AS page_durations ON page_durations.page_key = ${pageKey}
WHERE and(
    (event IN ${PAGE_PERFORMANCE_EVENTS}${match ? ` OR (${match})` : ''}),
    properties.$pathname IS NOT NULL,
    properties.$pathname != '',
    (${candidatePredicate}),
    (${full}),
    {filters}
)
GROUP BY "context.columns.breakdown_value"
HAVING uniqIf(person_id, (${HUMAN_VIEW}) AND ${cur}) > 0
ORDER BY ${orderExpr} ${orderBy.direction}
LIMIT ${PAGE_TABLE_LIMIT}
`
}

const buildOverviewHumanQuery = (window: PagePerformanceWindow, pathExpr: string): string => {
    const { cur, prev, full } = windowPredicates(window)
    const pageKey = pageKeyExpr(pathExpr)

    return `
SELECT
    uniqIf(person_id, (${HUMAN_VIEW}) AND ${cur}) AS visitors,
    uniqIf(person_id, (${HUMAN_VIEW}) AND ${prev}) AS visitors_previous,
    uniqIf(person_id, (${GOOGLE_VIEW}) AND ${cur}) AS google,
    uniqIf(person_id, (${GOOGLE_VIEW}) AND ${prev}) AS google_previous,
    uniqIf(person_id, (${AI_VIEW}) AND ${cur}) AS llm,
    uniqIf(person_id, (${AI_VIEW}) AND ${prev}) AS llm_previous,
    uniqIf(${pageKey}, (${HUMAN_VIEW}) AND ${cur}) AS pages
FROM events
WHERE and(
    event IN ${HUMAN_EVENTS},
    properties.$pathname IS NOT NULL,
    properties.$pathname != '',
    (${full}),
    {filters}
)
`
}

const buildOverviewCrawlerQuery = (window: PagePerformanceWindow): string => {
    const { cur, prev, full } = windowPredicates(window)

    return `
SELECT
    countIf((${CRAWLER}) AND ${cur}) AS crawls,
    countIf((${CRAWLER}) AND ${prev}) AS crawls_previous
FROM events
WHERE and(
    event IN ${PAGE_PERFORMANCE_EVENTS},
    properties.$pathname IS NOT NULL,
    properties.$pathname != '',
    (${full}),
    {filters}
)
`
}

const buildBreakdownQuery = (
    metric: PagePerformanceMetric,
    page: string,
    window: PagePerformanceWindow,
    pathExpr: string
): string | null => {
    const { cur } = windowPredicates(window)
    const pageMatch = `${pageKeyExpr(pathExpr)} = ${escapeHogQLString(page)}`

    if (metric === 'llm_referrals') {
        return `
SELECT
    coalesce(nullIf(session.$entry_referring_domain, ''), '(direct)') AS "Assistant",
    uniq(person_id) AS "Visitors"
FROM events
WHERE and(${AI_VIEW}, ${pageMatch}, (${cur}), {filters})
GROUP BY "Assistant"
ORDER BY "Visitors" DESC
LIMIT 10
`
    }
    if (metric === 'agent_crawls') {
        return `
SELECT
    \`$virt_bot_name\` AS "Crawler",
    \`$virt_traffic_category\` AS "Category",
    count() AS "Requests",
    max(timestamp) AS "Last seen"
FROM events
WHERE and(${CRAWLER}, event IN ${PAGE_PERFORMANCE_EVENTS}, ${pageMatch}, (${cur}), {filters})
GROUP BY "Crawler", "Category"
ORDER BY "Requests" DESC
LIMIT 50
`
    }
    return null
}

export const buildGoogleSearchConsoleQuery = (
    tableName: string,
    page: string,
    window: PagePerformanceWindow,
    isPathCleaningEnabled: boolean,
    pathCleaningFilters: { regex?: string; alias?: string }[] | undefined
): string => {
    const gscPath = buildPagePerformancePathExpr('path(page)', isPathCleaningEnabled, pathCleaningFilters)
    const gscPageKey = `concat(domain(page), ${gscPath})`
    const dateField = 'toDate(date)'
    const dateUpperBound = `${dateField} <= toDate(${tsLiteral(window.currentTo, window.timezone)})`
    const datePredicate = window.currentFrom
        ? `${dateField} >= toDate(${tsLiteral(window.currentFrom, window.timezone)}) AND ${dateUpperBound}`
        : dateUpperBound

    return `SELECT query AS "Query", sum(clicks) AS "Clicks", round(avg(position), 1) AS "Avg. position"
FROM ${escapeDottedHogQLIdentifier(tableName)}
WHERE ${gscPageKey} = ${escapeHogQLString(page)} AND (${datePredicate})
GROUP BY query
ORDER BY sum(clicks) DESC
LIMIT 20`
}

export interface pagePerformanceLogicValues {
    allActions: ActionType[]
    currentTeam: TeamPublicType | TeamType | null
    compareFilter: CompareFilter
    conversionGoal: WebAnalyticsConversionGoal | null
    dateFilter: DateFilterState
    filterTestAccounts: boolean
    isPathCleaningEnabled: boolean
    aiSectionQueries: AiSectionQueries
    breakdownModal: PagePerformanceBreakdownState | null
    breakdownQuery: DataTableNode | null
    candidatesError: string | null
    candidatesInput: string
    candidatesLoading: boolean
    footerText: string
    goalLabel: string | null
    orderBy: PagePerformanceOrderBy
    overviewCards: OverviewItem[]
    overviewCrawlerQuery: string
    overviewError: string | null
    overviewHumanQuery: string
    overviewInput: string
    overviewLoading: boolean
    overviewTotals: OverviewTotals | null
    pageCandidateQuery: WebStatsTableQuery
    pageCandidates: string[] | null
    pageTableQuery: DataTableNode
    pathExpr: string
    previousPathExpr: string
    window: PagePerformanceWindow
}

export interface pagePerformanceLogicActions {
    reloadAll: () => {}
    closeBreakdown: () => {
        value: true
    }
    loadOverview: () => {
        value: true
    }
    loadOverviewFailure: (error: string) => {
        error: string
    }
    loadOverviewSuccess: (overviewTotals: OverviewTotals) => {
        overviewTotals: OverviewTotals
    }
    loadCandidates: () => {
        value: true
    }
    loadCandidatesFailure: (error: string) => {
        error: string
    }
    loadCandidatesSuccess: (pageCandidates: string[]) => {
        pageCandidates: string[]
    }
    openBreakdown: (breakdown: PagePerformanceBreakdownState) => {
        breakdown: PagePerformanceBreakdownState
    }
    setOrderBy: (
        column: string,
        direction: 'ASC' | 'DESC'
    ) => {
        column: string
        direction: 'ASC' | 'DESC'
    }
}

export interface pagePerformanceLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        window: (
            dateFilter: DateFilterState,
            compareFilter: CompareFilter,
            currentTeam: TeamPublicType | TeamType | null
        ) => PagePerformanceWindow
        pathExpr: (isPathCleaningEnabled: boolean, currentTeam: TeamPublicType | TeamType | null) => string
        previousPathExpr: (isPathCleaningEnabled: boolean, currentTeam: TeamPublicType | TeamType | null) => string
        pageCandidateQuery: (dateFilter: DateFilterState, filterTestAccounts: boolean) => WebStatsTableQuery
        pageTableQuery: (
            window: PagePerformanceWindow,
            orderBy: PagePerformanceOrderBy,
            conversionGoal: WebAnalyticsConversionGoal | null,
            filterTestAccounts: boolean,
            pathExpr: string,
            previousPathExpr: string,
            pageCandidates: string[] | null
        ) => DataTableNode
        aiSectionQueries: (
            dateFilter: DateFilterState,
            filterTestAccounts: boolean,
            conversionGoal: WebAnalyticsConversionGoal | null,
            compareFilter: CompareFilter
        ) => AiSectionQueries
        overviewHumanQuery: (window: PagePerformanceWindow, pathExpr: string) => string
        overviewCrawlerQuery: (window: PagePerformanceWindow) => string
        overviewInput: (overviewHumanQuery: string, overviewCrawlerQuery: string, filterTestAccounts: boolean) => string
        candidatesInput: (pageCandidateQuery: WebStatsTableQuery) => string
        breakdownQuery: (
            breakdownModal: PagePerformanceBreakdownState | null,
            window: PagePerformanceWindow,
            filterTestAccounts: boolean,
            pathExpr: string
        ) => DataTableNode | null
        overviewCards: (overviewTotals: OverviewTotals | null, compareFilter: CompareFilter) => OverviewItem[]
        goalLabel: (conversionGoal: WebAnalyticsConversionGoal | null, allActions: ActionType[]) => string | null
        footerText: (
            overviewTotals: OverviewTotals | null,
            goalLabel: string | null,
            isPathCleaningEnabled: boolean
        ) => string
    }
}

export type pagePerformanceLogicType = MakeLogicType<
    pagePerformanceLogicValues,
    pagePerformanceLogicActions,
    Record<string, any>,
    pagePerformanceLogicMeta
>

export const pagePerformanceLogic = kea<pagePerformanceLogicType>([
    path(['scenes', 'webAnalytics', 'pagePerformanceLogic']),
    connect(() => ({
        actions: [dataNodeCollectionLogic({ key: WEB_ANALYTICS_DATA_COLLECTION_NODE_ID }), ['reloadAll']],
        values: [
            webAnalyticsLogic,
            [
                'dateFilter',
                'shouldFilterTestAccounts as filterTestAccounts',
                'compareFilter',
                'conversionGoal',
                'isPathCleaningEnabled',
            ],
            teamLogic,
            ['currentTeam'],
            actionsModel,
            ['actions as allActions'],
        ],
    })),
    actions({
        setOrderBy: (column: string, direction: 'ASC' | 'DESC') => ({ column, direction }),
        openBreakdown: (breakdown: PagePerformanceBreakdownState) => ({ breakdown }),
        closeBreakdown: true,
        loadOverview: true,
        loadOverviewFailure: (error: string) => ({ error }),
        loadOverviewSuccess: (overviewTotals: OverviewTotals) => ({ overviewTotals }),
        loadCandidates: true,
        loadCandidatesFailure: (error: string) => ({ error }),
        loadCandidatesSuccess: (pageCandidates: string[]) => ({ pageCandidates }),
    }),
    reducers({
        orderBy: [
            { column: 'visitors', direction: 'DESC' } as PagePerformanceOrderBy,
            {
                setOrderBy: (_, { column, direction }) => ({ column, direction }),
            },
        ],
        breakdownModal: [
            null as PagePerformanceBreakdownState | null,
            {
                openBreakdown: (_, { breakdown }) => breakdown,
                closeBreakdown: () => null,
            },
        ],
        overviewTotals: [
            null as OverviewTotals | null,
            {
                loadOverview: () => null,
                loadOverviewSuccess: (_, { overviewTotals }) => overviewTotals,
            },
        ],
        overviewError: [
            null as string | null,
            {
                loadOverview: () => null,
                loadOverviewFailure: (_, { error }) => error,
            },
        ],
        overviewLoading: [
            false,
            {
                loadOverview: () => true,
                loadOverviewSuccess: () => false,
                loadOverviewFailure: () => false,
            },
        ],
        pageCandidates: [
            null as string[] | null,
            {
                loadCandidates: () => null,
                loadCandidatesSuccess: (_, { pageCandidates }) => pageCandidates,
            },
        ],
        candidatesError: [
            null as string | null,
            {
                loadCandidates: () => null,
                loadCandidatesFailure: (_, { error }) => error,
            },
        ],
        candidatesLoading: [
            false,
            {
                loadCandidates: () => true,
                loadCandidatesSuccess: () => false,
                loadCandidatesFailure: () => false,
            },
        ],
    }),
    selectors(() => ({
        window: [
            (s) => [s.dateFilter, s.compareFilter, s.currentTeam],
            (
                dateFilter: DateFilterState,
                compareFilter: CompareFilter,
                currentTeam: TeamPublicType | TeamType | null
            ): PagePerformanceWindow =>
                resolvePagePerformanceWindow(dateFilter, compareFilter, currentTeam?.timezone ?? 'UTC'),
        ],
        pathExpr: [
            (s) => [s.isPathCleaningEnabled, s.currentTeam],
            (isPathCleaningEnabled: boolean, currentTeam: TeamType | null): string =>
                buildPagePerformancePathExpr(RAW_PATH, isPathCleaningEnabled, currentTeam?.path_cleaning_filters),
        ],
        previousPathExpr: [
            (s) => [s.isPathCleaningEnabled, s.currentTeam],
            (isPathCleaningEnabled: boolean, currentTeam: TeamType | null): string =>
                buildPagePerformancePathExpr(
                    'properties.$prev_pageview_pathname',
                    isPathCleaningEnabled,
                    currentTeam?.path_cleaning_filters
                ),
        ],
        pageCandidateQuery: [
            (s) => [s.dateFilter, s.filterTestAccounts],
            (dateFilter: DateFilterState, filterTestAccounts: boolean): WebStatsTableQuery => ({
                kind: NodeKind.WebStatsTableQuery,
                breakdownBy: WebStatsBreakdown.Page,
                dateRange: { date_from: dateFilter.dateFrom, date_to: dateFilter.dateTo },
                properties: [],
                compareFilter: { compare: false },
                doPathCleaning: false,
                filterTestAccounts,
                includeHost: true,
                limit: PAGE_CANDIDATE_LIMIT,
                orderBy: [WebAnalyticsOrderByFields.Visitors, 'DESC'],
                useWebAnalyticsPrecompute: true,
                tags: WEB_ANALYTICS_DEFAULT_QUERY_TAGS,
            }),
        ],
        pageTableQuery: [
            (s) => [
                s.window,
                s.orderBy,
                s.conversionGoal,
                s.filterTestAccounts,
                s.pathExpr,
                s.previousPathExpr,
                s.pageCandidates,
            ],
            (
                window: PagePerformanceWindow,
                orderBy: PagePerformanceOrderBy,
                conversionGoal: WebAnalyticsConversionGoal | null,
                filterTestAccounts: boolean,
                pathExpr: string,
                previousPathExpr: string,
                pageCandidates: string[] | null
            ): DataTableNode => ({
                kind: NodeKind.DataTableNode,
                source: {
                    kind: NodeKind.HogQLQuery,
                    query: buildPagePerformanceTableQuery(
                        window,
                        orderBy,
                        conversionGoal,
                        pathExpr,
                        previousPathExpr,
                        pageCandidates ?? []
                    ),
                    filters: { filterTestAccounts },
                    tags: WEB_ANALYTICS_DEFAULT_QUERY_TAGS,
                },
                embedded: true,
                showActions: false,
                columns: [
                    'context.columns.breakdown_value',
                    'context.columns.visitors',
                    'context.columns.google_search',
                    'context.columns.llm_referrals',
                    'context.columns.agent_crawls',
                    'context.columns.conversions',
                    'context.columns.avg_time',
                ],
            }),
        ],
        aiSectionQueries: [
            (s) => [s.dateFilter, s.filterTestAccounts, s.conversionGoal, s.compareFilter],
            (
                dateFilter: DateFilterState,
                filterTestAccounts: boolean,
                conversionGoal: WebAnalyticsConversionGoal | null,
                compareFilter: CompareFilter
            ): AiSectionQueries => {
                const dateRange = { date_from: dateFilter.dateFrom, date_to: dateFilter.dateTo }
                const interval = dateFilter.interval

                const referralFilters: WebAnalyticsPropertyFilters = [
                    {
                        key: '$channel_type',
                        value: ['AI'],
                        operator: PropertyOperator.Exact,
                        type: PropertyFilterType.Session,
                    },
                ]
                const crawlerFilters: WebAnalyticsPropertyFilters = [
                    {
                        key: '$virt_is_bot',
                        value: ['true'],
                        operator: PropertyOperator.Exact,
                        type: PropertyFilterType.Event,
                    },
                    {
                        key: '$virt_bot_name',
                        value: [''],
                        operator: PropertyOperator.IsNot,
                        type: PropertyFilterType.Event,
                    },
                    {
                        key: '$virt_traffic_category',
                        value: ['ai_crawler', 'ai_assistant', 'ai_search'],
                        operator: PropertyOperator.Exact,
                        type: PropertyFilterType.Event,
                    },
                ]

                const referralColumns = [
                    'breakdown_value',
                    'visitors',
                    'views',
                    ...(conversionGoal ? ['total_conversions', 'conversion_rate'] : []),
                    'cross_sell',
                ]

                const referralTable = (breakdownBy: WebStatsBreakdown): DataTableNode => ({
                    full: true,
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.WebStatsTableQuery,
                        properties: referralFilters,
                        breakdownBy,
                        dateRange,
                        compareFilter,
                        conversionGoal,
                        limit: 10,
                        filterTestAccounts,
                        tags: WEB_ANALYTICS_DEFAULT_QUERY_TAGS,
                    },
                    embedded: false,
                    showActions: true,
                    columns: referralColumns,
                })

                const crawlerTable = (breakdownBy: WebBotsBreakdown): DataTableNode => ({
                    full: true,
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.WebBotsTableQuery,
                        breakdownBy,
                        dateRange,
                        properties: crawlerFilters,
                        limit: 10,
                        filterTestAccounts,
                        tags: WEB_ANALYTICS_DEFAULT_QUERY_TAGS,
                    },
                    showActions: false,
                    embedded: false,
                })

                const crawlerRequestSeries: GroupNode[] = [
                    {
                        kind: NodeKind.GroupNode,
                        name: BOT_ANALYTICS_EVENTS.join(', '),
                        custom_name: 'Requests',
                        operator: FilterLogicalOperator.Or,
                        nodes: BOT_ANALYTICS_EVENTS.map(
                            (event): EventsNode => ({
                                event,
                                kind: NodeKind.EventsNode as const,
                                math: BaseMathType.TotalCount,
                                name: event,
                            })
                        ),
                        math: BaseMathType.TotalCount,
                    },
                ]

                return {
                    referralTrend: {
                        kind: NodeKind.InsightVizNode,
                        source: {
                            kind: NodeKind.TrendsQuery,
                            dateRange,
                            interval,
                            series: [
                                {
                                    kind: NodeKind.EventsNode,
                                    event: '$pageview',
                                    name: '$pageview',
                                    math: BaseMathType.UniqueSessions,
                                },
                            ],
                            trendsFilter: {
                                display: ChartDisplayType.ActionsLineGraph,
                                showLegend: true,
                            } as TrendsFilter,
                            breakdownFilter: getWebAnalyticsBreakdownFilter(WebStatsBreakdown.InitialReferringDomain),
                            properties: referralFilters,
                            filterTestAccounts,
                            tags: WEB_ANALYTICS_DEFAULT_QUERY_TAGS,
                        },
                        hidePersonsModal: true,
                        embedded: true,
                    },
                    byEngine: referralTable(WebStatsBreakdown.InitialReferringDomain),
                    landingPages: referralTable(WebStatsBreakdown.InitialPage),
                    crawlerTrend: {
                        kind: NodeKind.InsightVizNode,
                        source: {
                            kind: NodeKind.TrendsQuery,
                            dateRange,
                            interval,
                            series: crawlerRequestSeries,
                            trendsFilter: { display: ChartDisplayType.ActionsLineGraph } as TrendsFilter,
                            properties: crawlerFilters,
                            filterTestAccounts,
                            tags: WEB_ANALYTICS_DEFAULT_QUERY_TAGS,
                        },
                        hidePersonsModal: true,
                        embedded: true,
                    },
                    byCrawler: crawlerTable(WebBotsBreakdown.Crawler),
                    crawledPages: crawlerTable(WebBotsBreakdown.Path),
                }
            },
        ],
        overviewHumanQuery: [
            (s) => [s.window, s.pathExpr],
            (window: PagePerformanceWindow, pathExpr: string): string => buildOverviewHumanQuery(window, pathExpr),
        ],
        overviewCrawlerQuery: [
            (s) => [s.window],
            (window: PagePerformanceWindow): string => buildOverviewCrawlerQuery(window),
        ],
        overviewInput: [
            (s) => [s.overviewHumanQuery, s.overviewCrawlerQuery, s.filterTestAccounts],
            (overviewHumanQuery: string, overviewCrawlerQuery: string, filterTestAccounts: boolean): string =>
                JSON.stringify([overviewHumanQuery, overviewCrawlerQuery, filterTestAccounts]),
        ],
        candidatesInput: [
            (s) => [s.pageCandidateQuery],
            (pageCandidateQuery: WebStatsTableQuery): string => JSON.stringify(pageCandidateQuery),
        ],
        breakdownQuery: [
            (s) => [s.breakdownModal, s.window, s.filterTestAccounts, s.pathExpr],
            (
                breakdownModal: PagePerformanceBreakdownState | null,
                window: PagePerformanceWindow,
                filterTestAccounts: boolean,
                pathExpr: string
            ): DataTableNode | null => {
                if (!breakdownModal) {
                    return null
                }
                const query = buildBreakdownQuery(breakdownModal.metric, breakdownModal.page, window, pathExpr)
                if (!query) {
                    return null
                }
                return {
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.HogQLQuery,
                        query,
                        filters: { filterTestAccounts },
                        tags: WEB_ANALYTICS_DEFAULT_QUERY_TAGS,
                    },
                    embedded: true,
                    showActions: false,
                }
            },
        ],
        overviewCards: [
            (s) => [s.overviewTotals, s.compareFilter],
            (overviewTotals: OverviewTotals | null, compareFilter: CompareFilter): OverviewItem[] => {
                const compare = compareFilter.compare !== false
                const card = (key: string, value: number, previous: number): OverviewItem => ({
                    key,
                    value,
                    previous: compare ? previous : undefined,
                    changeFromPreviousPct:
                        compare && previous > 0 ? Math.round(((value - previous) / previous) * 100) : undefined,
                    kind: 'unit',
                })
                const t = overviewTotals
                if (!t) {
                    return []
                }
                return [
                    card('visitors', t.visitors, t.visitorsPrevious),
                    card('google_search', t.google, t.googlePrevious),
                    card('llm_referrals', t.llm, t.llmPrevious),
                    card('agent_crawls', t.crawls, t.crawlsPrevious),
                ]
            },
        ],
        goalLabel: [
            (s) => [s.conversionGoal, s.allActions],
            (conversionGoal: WebAnalyticsConversionGoal | null, allActions: ActionType[]): string | null => {
                if (!conversionGoal) {
                    return null
                }
                if ('actionId' in conversionGoal) {
                    return allActions.find((a) => a.id === conversionGoal.actionId)?.name ?? 'Conversion goal'
                }
                return conversionGoal.customEventName
            },
        ],
        footerText: [
            (s) => [s.overviewTotals, s.goalLabel, s.isPathCleaningEnabled],
            (
                overviewTotals: OverviewTotals | null,
                goalLabel: string | null,
                isPathCleaningEnabled: boolean
            ): string => {
                const pages = overviewTotals?.pages ?? 0
                return [
                    `${pages} ${pages === 1 ? 'page' : 'pages'}`,
                    `conversion goal: ${goalLabel ?? 'not set'}`,
                    `path cleaning ${isPathCleaningEnabled ? 'on' : 'off'}`,
                ].join(' · ')
            },
        ],
    })),
    listeners(({ values, actions, cache }) => ({
        loadOverview: async (_, breakpoint) => {
            await breakpoint(300)
            cache.disposables.dispose('overviewRequest')
            const abortController = new AbortController()
            cache.disposables.add(() => () => abortController.abort(), 'overviewRequest', {
                pauseOnPageHidden: false,
            })

            const humanNode: HogQLQuery = {
                kind: NodeKind.HogQLQuery,
                query: values.overviewHumanQuery,
                filters: { filterTestAccounts: values.filterTestAccounts },
                tags: WEB_ANALYTICS_DEFAULT_QUERY_TAGS,
            }
            const crawlerNode: HogQLQuery = {
                kind: NodeKind.HogQLQuery,
                query: values.overviewCrawlerQuery,
                filters: { filterTestAccounts: values.filterTestAccounts },
                tags: WEB_ANALYTICS_DEFAULT_QUERY_TAGS,
            }
            try {
                const [humanResponse, crawlerResponse] = await Promise.all([
                    performQuery(humanNode, { signal: abortController.signal }),
                    performQuery(crawlerNode, { signal: abortController.signal }),
                ])
                breakpoint()
                const readColumn = (response: typeof humanResponse): ((name: string) => number) => {
                    const row = response.results?.[0] ?? []
                    const columns: string[] = response.columns ?? []
                    return (name: string): number => {
                        const idx = columns.indexOf(name)
                        return idx >= 0 ? Number(row[idx] ?? 0) : 0
                    }
                }
                const human = readColumn(humanResponse)
                const crawler = readColumn(crawlerResponse)
                actions.loadOverviewSuccess({
                    visitors: human('visitors'),
                    visitorsPrevious: human('visitors_previous'),
                    google: human('google'),
                    googlePrevious: human('google_previous'),
                    llm: human('llm'),
                    llmPrevious: human('llm_previous'),
                    crawls: crawler('crawls'),
                    crawlsPrevious: crawler('crawls_previous'),
                    pages: human('pages'),
                })
            } catch (error) {
                if ((error instanceof Error && isBreakpoint(error)) || isAbortedRequest(error)) {
                    return
                }
                actions.loadOverviewFailure(error instanceof Error ? error.message : 'Could not load page performance')
            }
        },
        loadCandidates: async (_, breakpoint) => {
            await breakpoint(300)
            cache.disposables.dispose('candidatesRequest')
            const abortController = new AbortController()
            cache.disposables.add(() => () => abortController.abort(), 'candidatesRequest', {
                pauseOnPageHidden: false,
            })
            try {
                const candidatesResponse = await performQuery(values.pageCandidateQuery, {
                    signal: abortController.signal,
                })
                breakpoint()
                const pageCandidates = (candidatesResponse.results ?? []).flatMap((candidate) => {
                    if (!Array.isArray(candidate) || typeof candidate[0] !== 'string' || candidate[0] === '') {
                        return []
                    }
                    return [candidate[0]]
                })
                actions.loadCandidatesSuccess(pageCandidates)
            } catch (error) {
                if ((error instanceof Error && isBreakpoint(error)) || isAbortedRequest(error)) {
                    return
                }
                actions.loadCandidatesFailure(
                    error instanceof Error ? error.message : 'Could not load page performance'
                )
            }
        },
        reloadAll: () => {
            actions.loadOverview()
            actions.loadCandidates()
        },
    })),
    subscriptions(({ actions }) => ({
        overviewInput: () => {
            actions.loadOverview()
        },
        candidatesInput: () => {
            actions.loadCandidates()
        },
    })),
    afterMount(({ actions }) => {
        actions.loadOverview()
        actions.loadCandidates()
    }),
])

export const createPagePerformanceInsightProps = (tile: TileId, tab?: string): InsightLogicProps => ({
    dashboardItemId: getDashboardItemId(tile, tab, false),
    loadPriority: loadPriorityMap[tile],
    dataNodeCollectionId: WEB_ANALYTICS_DATA_COLLECTION_NODE_ID,
})
