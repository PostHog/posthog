import clsx from 'clsx'
import {
    actions,
    afterMount,
    beforeUnmount,
    connect,
    kea,
    key,
    listeners,
    path,
    props,
    propsChanged,
    reducers,
    selectors,
} from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

import api, { ApiMethodOptions } from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { shouldCancelQuery, uuid } from 'lib/utils'
import { ConcurrencyController } from 'lib/utils/concurrencyController'
import { UNSAVED_INSIGHT_MIN_REFRESH_INTERVAL_MINUTES } from 'scenes/insights/insightLogic'
import { compareDataNodeQuery, haveVariablesOrFiltersChanged, validateQuery } from 'scenes/insights/utils/queryUtils'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { DataNodeCollectionProps, dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { removeExpressionComment } from '~/queries/nodes/DataTable/utils'
import { performQuery } from '~/queries/query'
import {
    ActorsQuery,
    ActorsQueryResponse,
    AnyResponseType,
    DashboardFilter,
    DataNode,
    ErrorTrackingQuery,
    ErrorTrackingQueryResponse,
    EventsQuery,
    EventsQueryResponse,
    GroupsQuery,
    GroupsQueryResponse,
    HogQLQueryModifiers,
    HogQLQueryResponse,
    HogQLVariable,
    InsightVizNode,
    MarketingAnalyticsTableQuery,
    MarketingAnalyticsTableQueryResponse,
    NodeKind,
    PersonsNode,
    QueryStatus,
    QueryTiming,
    RefreshType,
    TracesQuery,
    TracesQueryResponse,
} from '~/queries/schema/schema-general'
import {
    isActorsQuery,
    isErrorTrackingQuery,
    isEventsQuery,
    isGroupsQuery,
    isHogQLQuery,
    isInsightActorsQuery,
    isInsightQueryNode,
    isMarketingAnalyticsTableQuery,
    isPersonsNode,
    isTracesQuery,
} from '~/queries/utils'
import { TeamType } from '~/types'

import type { dataNodeLogicType } from './dataNodeLogicType'

export interface DataNodeLogicProps {
    key: string
    query: DataNode
    /** Cached results when fetching nodes in bulk (list endpoint), sharing or exporting. */
    cachedResults?: AnyResponseType
    /** Disabled data fetching and only allow cached results. */
    doNotLoad?: boolean
    /** Refresh behaviour for queries. */
    refresh?: RefreshType
    /** Callback when data is successfully loader or provided from cache. */
    onData?: (data: Record<string, unknown> | null | undefined) => void
    /** Callback when an error is returned */
    onError?: (error: string | null) => void
    /** Load priority. Higher priority (smaller number) queries will be loaded first. */
    loadPriority?: number
    /** Override modifiers when making the request */
    modifiers?: HogQLQueryModifiers

    dataNodeCollectionId?: string

    /** Dashboard filters to override the ones in the query */
    filtersOverride?: DashboardFilter | null
    /** Dashboard variables to override the ones in the query */
    variablesOverride?: Record<string, HogQLVariable> | null

    /** Whether to automatically load data when the query changes. Used for manual override in SQL editor */
    autoLoad?: boolean
    /** Override the maximum pagination limit. */
    maxPaginationLimit?: number
}

export const AUTOLOAD_INTERVAL = 30000
const LOAD_MORE_ROWS_LIMIT = 10000

const concurrencyController = new ConcurrencyController(1)
const webAnalyticsConcurrencyController = new ConcurrencyController(3)
const webAnalyticsPreAggConcurrencyController = new ConcurrencyController(5)

function getConcurrencyController(
    query: DataNode,
    currentTeam: TeamType,
    featureFlags: Record<string, boolean | string>
): ConcurrencyController {
    const mountedSceneLogic = sceneLogic.findMounted()
    const activeScene = mountedSceneLogic?.values.activeSceneId
    if (
        activeScene === Scene.WebAnalytics &&
        featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_HIGHER_CONCURRENCY] &&
        !currentTeam?.modifiers?.useWebAnalyticsPreAggregatedTables
    ) {
        return webAnalyticsConcurrencyController
    }

    if (
        currentTeam?.modifiers?.useWebAnalyticsPreAggregatedTables &&
        [NodeKind.WebOverviewQuery, NodeKind.WebStatsTableQuery, NodeKind.InsightVizNode].includes(query.kind)
    ) {
        return webAnalyticsPreAggConcurrencyController
    }
    return concurrencyController
}

function addModifiers(query: DataNode, modifiers?: HogQLQueryModifiers): DataNode {
    if (!modifiers) {
        return query
    }
    return {
        ...query,
        modifiers: { ...query.modifiers, ...modifiers },
    }
}

function addTags<T extends Record<string, any>>(query: DataNode<T>): DataNode<T> {
    // find the currently mounted scene logic to get the active scene, but don't use the kea connect()
    // method to do this as we don't want to mount the sceneLogic if it isn't already mounted
    const mountedSceneLogic = sceneLogic.findMounted()
    const activeScene = mountedSceneLogic?.values.activeSceneId

    const tags = query.tags ? { ...query.tags } : {}
    if (!tags.scene && activeScene) {
        tags.scene = activeScene
    }
    const result: DataNode<T> = {
        ...query,
        tags,
    }
    if (result.tags && Object.keys(result.tags).length === 0) {
        delete result.tags // Remove empty tags object
    }
    return result
}

export const dataNodeLogic = kea<dataNodeLogicType>([
    path(['queries', 'nodes', 'dataNodeLogic']),
    key((props) => props.key),
    connect((props: DataNodeLogicProps) => ({
        values: [userLogic, ['user'], teamLogic, ['currentTeam', 'currentTeamId'], featureFlagLogic, ['featureFlags']],
        actions: [
            dataNodeCollectionLogic({ key: props.dataNodeCollectionId || props.key } as DataNodeCollectionProps),
            [
                'mountDataNode',
                'unmountDataNode',
                'collectionNodeLoadData',
                'collectionNodeLoadDataSuccess',
                'collectionNodeLoadDataFailure',
            ],
        ],
    })),
    props({ query: {}, variablesOverride: undefined, autoLoad: true } as DataNodeLogicProps),
    propsChanged(({ actions, props }, oldProps) => {
        if (!props.query) {
            return // Can't do anything without a query
        }
        if (oldProps.query?.kind && props.query.kind !== oldProps.query.kind) {
            actions.clearResponse()
        }
        const hasQueryChanged = !compareDataNodeQuery(props.query, oldProps.query, {
            ignoreVisualizationOnlyChanges: true,
        })
        const queryVarsHaveChanged = haveVariablesOrFiltersChanged(props.query, oldProps.query)

        const queryStatus = (props.cachedResults?.query_status || null) as QueryStatus | null
        if (hasQueryChanged && queryStatus?.complete === false) {
            // If there is an incomplete query, load the data with the same query_id which should return its status
            // We need to force a refresh in this case
            const refreshType =
                isInsightQueryNode(props.query) || isHogQLQuery(props.query) ? 'force_async' : 'force_blocking'
            actions.loadData(refreshType, queryStatus.id)
        } else if (
            hasQueryChanged &&
            props.autoLoad &&
            !(props.cachedResults && props.key.includes('dashboard')) && // Don't load data on dashboard if cached results are available
            (!props.cachedResults ||
                (isInsightQueryNode(props.query) &&
                    typeof props.cachedResults === 'object' &&
                    !('result' in props.cachedResults) &&
                    !('results' in props.cachedResults)))
        ) {
            // For normal loads, use appropriate refresh type
            let refreshType: RefreshType
            if (queryVarsHaveChanged) {
                refreshType =
                    isInsightQueryNode(props.query) || isHogQLQuery(props.query) ? 'force_async' : 'force_blocking'
            } else {
                refreshType = isInsightQueryNode(props.query) || isHogQLQuery(props.query) ? 'async' : 'blocking'
            }

            actions.loadData(refreshType)
        } else if (props.cachedResults) {
            // Use cached results if available, otherwise this logic will load the data again
            actions.setResponse(props.cachedResults)
        }
    }),
    actions({
        loadData: (
            refresh?: RefreshType,
            alreadyRunningQueryId?: string,
            overrideQuery?: DataNode<Record<string, any>>
        ) => ({
            refresh,
            queryId: alreadyRunningQueryId || uuid(),
            pollOnly: !!alreadyRunningQueryId,
            overrideQuery,
        }),
        abortAnyRunningQuery: true,
        abortQuery: (payload: { queryId: string }) => payload,
        cancelQuery: true,
        setResponse: (response: Exclude<AnyResponseType, undefined>) => response,
        clearResponse: true,
        startAutoLoad: true,
        stopAutoLoad: true,
        toggleAutoLoad: true,
        highlightRows: (rows: any[]) => ({ rows }),
        setElapsedTime: (elapsedTime: number) => ({ elapsedTime }),
        setPollResponse: (status: QueryStatus | null) => ({ status }),
        setLoadingTime: (seconds: number) => ({ seconds }),
        resetLoadingTimer: true,
        setQueryLogQueryId: (queryId: string) => ({ queryId }),
    }),
    loaders(({ actions, cache, values, props }) => ({
        response: [
            props.cachedResults ?? null,
            {
                setResponse: (response) => response,
                clearResponse: () => null,
                loadData: async ({ refresh: refreshArg, queryId, pollOnly, overrideQuery }, breakpoint) => {
                    const query = addTags(overrideQuery ?? props.query)

                    // Use the explicit refresh type passed, or determine it based on query type
                    // Default to non-force variants
                    let refresh: RefreshType = refreshArg ?? (isInsightQueryNode(query) ? 'async' : 'blocking')

                    if (!pollOnly && ['async', 'force_async'].includes(refresh)) {
                        refresh = refresh.startsWith('force_') ? 'force_blocking' : 'blocking'
                    }

                    if (props.doNotLoad) {
                        return props.cachedResults
                    }

                    const queryStatus = (props.cachedResults?.query_status || null) as QueryStatus | null
                    if (
                        props.cachedResults &&
                        refresh !== 'force_async' &&
                        refresh !== 'force_blocking' &&
                        queryStatus?.complete !== false
                    ) {
                        if (
                            typeof props.cachedResults === 'object' &&
                            ('result' in props.cachedResults || 'results' in props.cachedResults)
                        ) {
                            return props.cachedResults
                        }
                    }

                    // if no query, return null
                    if ('query' in query) {
                        if (!query.query) {
                            return null
                        }
                    }

                    if (!values.currentTeamId) {
                        // if shared/exported, the team is not loaded
                        return null
                    }

                    if (query === undefined || Object.keys(query).length === 0) {
                        // no need to try and load a query before properly initialized
                        return null
                    }

                    if (!validateQuery(query)) {
                        return null
                    }

                    actions.abortAnyRunningQuery()
                    actions.setPollResponse(null)
                    const abortController = new AbortController()
                    cache.abortController = abortController
                    const methodOptions: ApiMethodOptions = {
                        signal: cache.abortController.signal,
                    }
                    try {
                        // For shared contexts, create a minimal team object if needed
                        const response = await getConcurrencyController(
                            query,
                            values.currentTeam as TeamType,
                            values.featureFlags
                        ).run({
                            debugTag: query.kind,
                            abortController,
                            priority: props.loadPriority,
                            fn: async (): Promise<{ duration: number; data: Record<string, any> }> => {
                                const now = performance.now()
                                try {
                                    breakpoint()
                                    const data =
                                        (await performQuery<DataNode>(
                                            addModifiers(query, props.modifiers),
                                            methodOptions,
                                            refresh,
                                            queryId,
                                            actions.setPollResponse,
                                            props.filtersOverride,
                                            props.variablesOverride,
                                            pollOnly
                                        )) ?? null
                                    const duration = performance.now() - now
                                    return { data, duration }
                                } catch (error: any) {
                                    const duration = performance.now() - now
                                    error.duration = duration
                                    throw error
                                }
                            },
                        })
                        breakpoint()
                        actions.setElapsedTime(response.duration)
                        return response.data
                    } catch (error: any) {
                        if (error.duration) {
                            actions.setElapsedTime(error.duration)
                        }
                        error.queryId = queryId
                        if (shouldCancelQuery(error)) {
                            actions.abortQuery({ queryId })
                        }
                        breakpoint()
                        throw error
                    }
                },
                loadNewData: async () => {
                    if (props.cachedResults) {
                        return props.cachedResults
                    }

                    if (!values.canLoadNewData || values.dataLoading) {
                        return values.response
                    }
                    if (isEventsQuery(props.query) && values.newQuery) {
                        const now = performance.now()
                        const newResponse =
                            (await performQuery(
                                addModifiers(values.newQuery, props.modifiers),
                                undefined,
                                props.refresh
                            )) ?? null
                        actions.setElapsedTime(performance.now() - now)
                        if (values.response === null) {
                            return newResponse
                        }
                        if (newResponse?.results) {
                            actions.highlightRows(newResponse?.results)
                        }
                        const currentResults = ((values.response || { results: [] }) as EventsQueryResponse).results
                        return {
                            ...values.response,
                            results: [...(newResponse?.results ?? []), ...currentResults],
                        }
                    }
                    return values.response
                },
                loadNextData: async () => {
                    if (props.cachedResults) {
                        return props.cachedResults
                    }

                    if (!values.canLoadNextData || values.dataLoading || !values.nextQuery) {
                        return values.response
                    }
                    // TODO: unify when we use the same backend endpoint for both
                    const now = performance.now()
                    if (
                        isEventsQuery(props.query) ||
                        isActorsQuery(props.query) ||
                        isGroupsQuery(props.query) ||
                        isTracesQuery(props.query) ||
                        isErrorTrackingQuery(props.query) ||
                        isMarketingAnalyticsTableQuery(props.query)
                    ) {
                        const newResponse =
                            (await performQuery(
                                addModifiers(values.nextQuery, props.modifiers),
                                undefined,
                                props.refresh
                            )) ?? null
                        actions.setElapsedTime(performance.now() - now)
                        const queryResponse = values.response as
                            | EventsQueryResponse
                            | ActorsQueryResponse
                            | GroupsQueryResponse
                            | ErrorTrackingQueryResponse
                            | TracesQueryResponse
                            | MarketingAnalyticsTableQueryResponse

                        let results = [...(queryResponse?.results ?? []), ...(newResponse?.results ?? [])]

                        if (isErrorTrackingQuery(props.query)) {
                            results = dedupeResults(results, 'id')
                        }

                        return {
                            ...queryResponse,
                            results: results,
                            hasMore: newResponse?.hasMore,
                        }
                    } else if (isPersonsNode(props.query)) {
                        const newResponse =
                            (await performQuery(
                                addModifiers(values.nextQuery, props.modifiers),
                                undefined,
                                props.refresh
                            )) ?? null
                        actions.setElapsedTime(performance.now() - now)
                        if (Array.isArray(values.response)) {
                            // help typescript by asserting we can't have an array here
                            throw new Error('Unexpected response type for persons node query')
                        }
                        return {
                            ...values.response,
                            results: [
                                ...(values.response && 'results' in values.response
                                    ? (values.response?.results ?? [])
                                    : []),
                                ...(newResponse?.results ?? []),
                            ],
                            next: newResponse?.next,
                        }
                    }
                    return values.response
                },
            },
        ],
        queryLog: [
            null as HogQLQueryResponse | null,
            {
                loadQueryLog: async (queryId, breakpoint) => {
                    if (!queryId) {
                        throw new Error('No query ID provided')
                    }
                    if (!values.featureFlags[FEATURE_FLAGS.QUERY_EXECUTION_DETAILS]) {
                        return null
                    }

                    try {
                        const result = await api.queryLog.get(queryId)
                        if (result?.results && result.results.length > 0) {
                            actions.setQueryLogQueryId(queryId)
                        }
                        return result
                    } catch (e: any) {
                        console.warn('Failed to get query execution details', e)
                        e.queryId = queryId
                        breakpoint()
                        throw e
                    }
                },
            },
        ],
    })),
    reducers(({ props }) => ({
        isRefresh: [
            false,
            {
                loadData: (_, { refresh }) => !!refresh,
            },
        ],
        dataLoading: [
            false,
            {
                loadData: () => true,
                loadDataSuccess: () => false,
                loadDataFailure: () => false,
                cancelQuery: () => false,
            },
        ],
        queryId: [
            null as null | string,
            {
                loadData: (_, { queryId }) => queryId,
            },
        ],
        newDataLoading: [
            false,
            {
                loadNewData: () => true,
                loadNewDataSuccess: () => false,
                loadNewDataFailure: () => false,
                cancelQuery: () => false,
            },
        ],
        nextDataLoading: [
            false,
            {
                loadNextData: () => true,
                loadNextDataSuccess: () => false,
                loadNextDataFailure: () => false,
                cancelQuery: () => false,
            },
        ],
        queryCancelled: [
            false,
            {
                loadNextData: () => false,
                loadNewData: () => false,
                loadData: () => false,
                cancelQuery: () => true,
            },
        ],
        pollResponse: [
            null as null | Record<string, QueryStatus | null>,
            {
                setPollResponse: (state, { status }) => {
                    return { status, previousStatus: state && state.status }
                },
            },
        ],
        autoLoadToggled: [
            false,
            // store the 'autoload toggle' state in localstorage, separately for each data node kind
            {
                persist: true,
                storageKey: clsx('queries.nodes.dataNodeLogic.autoLoadToggled', props.query?.kind, {
                    action: isEventsQuery(props.query) && props.query.actionId,
                    person: isEventsQuery(props.query) && props.query.personId,
                }),
            },
            { toggleAutoLoad: (state) => !state },
        ],
        autoLoadStarted: [false, { startAutoLoad: () => true, stopAutoLoad: () => false }],
        highlightedRows: [
            new Set<any>(),
            {
                highlightRows: (state, { rows }) => new Set([...Array.from(state), ...rows]),
                loadDataSuccess: () => new Set(),
            },
        ],
        loadingStart: [
            null as number | null,
            {
                setElapsedTime: () => null,
                loadData: () => performance.now(),
                loadNewData: () => performance.now(),
                loadNextData: () => performance.now(),
                cancelQuery: () => null,
            },
        ],
        response: {
            // Clear the response if a failure to avoid showing inconsistencies in the UI
            loadDataFailure: () => null,
        },
        responseErrorObject: [
            null as Record<string, any> | null,
            {
                loadData: () => null,
                loadDataFailure: (_, { errorObject }) => errorObject,
                loadDataSuccess: () => null,
            },
        ],
        responseError: [
            null as string | null,
            {
                loadData: () => null,
                loadNewData: () => null,
                loadDataFailure: (_, { error, errorObject }) => {
                    if (errorObject && 'error' in errorObject) {
                        return errorObject.error ?? 'Error loading data'
                    }
                    if (errorObject && 'detail' in errorObject) {
                        return errorObject.detail ?? 'Error loading data'
                    }
                    return error ?? 'Error loading data'
                },
                loadNewDataFailure: (_, { error, errorObject }) => {
                    if (errorObject && 'error' in errorObject) {
                        return errorObject.error ?? 'Error loading data'
                    }
                    if (errorObject && 'detail' in errorObject) {
                        return errorObject.detail ?? 'Error loading data'
                    }
                    return error ?? 'Error loading data'
                },
                loadDataSuccess: (_, { response }) =>
                    response && 'error' in response ? (response.error ?? null) : null,
                loadNewDataSuccess: (_, { response }) =>
                    response && 'error' in response ? (response.error ?? null) : null,
            },
        ],
        elapsedTime: [
            null as number | null,
            {
                setElapsedTime: (_, { elapsedTime }) => elapsedTime,
                loadData: () => null,
                loadNewData: () => null,
                loadNextData: () => null,
                cancelQuery: () => null,
            },
        ],
        loadingTimeSeconds: [
            0,
            {
                loadData: () => 0,
                loadDataSuccess: () => 0,
                loadDataFailure: () => 0,
                setLoadingTime: (_, { seconds }) => seconds,
                cancelQuery: () => 0,
            },
        ],
        queryLogQueryId: [
            null as string | null,
            {
                setQueryLogQueryId: (_, { queryId }) => queryId,
                loadData: () => null,
            },
        ],
    })),
    selectors(({ cache }) => ({
        variableOverridesAreSet: [
            (_, p) => [p.variablesOverride ?? (() => ({}))],
            (variablesOverride) => !!variablesOverride,
        ],
        isShowingCachedResults: [
            (s) => [(_, props) => props.cachedResults ?? null, (_, props) => props.query, s.isRefresh],
            (cachedResults: AnyResponseType | null, query: DataNode, isRefresh): boolean => {
                if (isRefresh) {
                    return false
                }

                return (
                    !!cachedResults ||
                    (cache.localResults && 'query' in query && JSON.stringify(query.query) in cache.localResults)
                )
            },
        ],
        query: [(_, p) => [p.query], (query) => query],
        newQuery: [
            (s, p) => [p.query, s.response],
            (query, response): DataNode | null => {
                if (!isEventsQuery(query)) {
                    return null
                }
                if (isEventsQuery(query) && !query.before) {
                    const sortKey = query.orderBy?.[0] ?? 'timestamp DESC'
                    if (sortKey === 'timestamp DESC') {
                        const sortColumnIndex = query.select
                            .map((hql) => removeExpressionComment(hql))
                            .indexOf('timestamp')
                        if (sortColumnIndex !== -1) {
                            const typedResults = (response as EventsQuery['response'])?.results
                            const firstTimestamp = typedResults?.[0]?.[sortColumnIndex]
                            if (firstTimestamp) {
                                const nextQuery: EventsQuery = { ...query, after: firstTimestamp }
                                return nextQuery
                            }
                            return query
                        }
                    }
                }
                return null
            },
        ],
        canLoadNewData: [
            (s) => [s.newQuery, s.isShowingCachedResults],
            (newQuery, isShowingCachedResults) => (isShowingCachedResults ? false : !!newQuery),
        ],
        nextQuery: [
            (s, p) => [
                p.query,
                s.response,
                s.responseError,
                s.dataLoading,
                s.isShowingCachedResults,
                (_, props) => props.maxPaginationLimit,
            ],
            (
                query,
                response,
                responseError,
                dataLoading,
                isShowingCachedResults,
                maxPaginationLimit
            ): DataNode | null => {
                if (isShowingCachedResults) {
                    return null
                }

                const effectivePaginationLimit = maxPaginationLimit ?? LOAD_MORE_ROWS_LIMIT
                if (
                    (isEventsQuery(query) ||
                        isActorsQuery(query) ||
                        isGroupsQuery(query) ||
                        isErrorTrackingQuery(query) ||
                        isTracesQuery(query) ||
                        isMarketingAnalyticsTableQuery(query)) &&
                    !responseError &&
                    !dataLoading
                ) {
                    if (
                        (
                            response as
                                | EventsQueryResponse
                                | ActorsQueryResponse
                                | GroupsQueryResponse
                                | ErrorTrackingQueryResponse
                                | TracesQueryResponse
                                | MarketingAnalyticsTableQueryResponse
                        )?.hasMore
                    ) {
                        const sortKey = isTracesQuery(query) ? null : (query.orderBy?.[0] ?? 'timestamp DESC')
                        if (isEventsQuery(query) && sortKey === 'timestamp DESC') {
                            const typedResults = (response as EventsQueryResponse)?.results
                            const sortColumnIndex = query.select
                                .map((hql) => removeExpressionComment(hql))
                                .indexOf('timestamp')
                            if (sortColumnIndex !== -1) {
                                const lastTimestamp = typedResults?.[typedResults.length - 1]?.[sortColumnIndex]
                                if (lastTimestamp) {
                                    const newQuery: EventsQuery = {
                                        ...query,
                                        before: lastTimestamp,
                                        limit: Math.max(
                                            100,
                                            Math.min(2 * (typedResults?.length || 100), effectivePaginationLimit)
                                        ),
                                    }
                                    return newQuery
                                }
                            }
                        } else {
                            const typedResults = (
                                response as
                                    | EventsQueryResponse
                                    | ActorsQueryResponse
                                    | GroupsQueryResponse
                                    | ErrorTrackingQueryResponse
                                    | TracesQueryResponse
                                    | MarketingAnalyticsTableQueryResponse
                            )?.results
                            return {
                                ...query,
                                offset: typedResults?.length || 0,
                                limit: Math.max(
                                    100,
                                    Math.min(2 * (typedResults?.length || 100), effectivePaginationLimit)
                                ),
                            } as
                                | EventsQuery
                                | ActorsQuery
                                | GroupsQuery
                                | ErrorTrackingQuery
                                | TracesQuery
                                | MarketingAnalyticsTableQuery
                        }
                    }
                }
                if (isPersonsNode(query) && response && !responseError && 'next' in response && response.next) {
                    const personsResults = (response as PersonsNode['response'])?.results
                    const nextQuery: PersonsNode = {
                        ...query,
                        limit: query.limit || 100,
                        offset: personsResults.length,
                    }
                    return nextQuery
                }
                return null
            },
        ],
        canLoadNextData: [
            (s) => [s.nextQuery, s.isShowingCachedResults],
            (nextQuery, isShowingCachedResults) => (isShowingCachedResults ? false : !!nextQuery),
        ],
        hasMoreData: [
            (s) => [s.response],
            (response): boolean => {
                return response && 'hasMore' in response && response.hasMore
            },
        ],
        dataLimit: [
            // get limit from response
            (s) => [s.response],
            (response): number | null => {
                return response && 'limit' in response ? (response.limit ?? null) : null
            },
        ],
        backToSourceQuery: [
            (s) => [s.query],
            (query): InsightVizNode | null => {
                if (isActorsQuery(query) && isInsightActorsQuery(query.source) && !!query.source.source) {
                    const insightQuery = query.source.source
                    const insightVizNode: InsightVizNode = {
                        kind: NodeKind.InsightVizNode,
                        source: insightQuery,
                        full: true,
                    }
                    return insightVizNode
                }
                return null
            },
        ],
        autoLoadRunning: [
            (s) => [s.autoLoadToggled, s.autoLoadStarted, s.dataLoading],
            (autoLoadToggled, autoLoadStarted, dataLoading) => autoLoadToggled && autoLoadStarted && !dataLoading,
        ],
        lastRefresh: [
            (s) => [s.response],
            (response): string | null => {
                return response && 'last_refresh' in response ? response.last_refresh : null
            },
        ],
        nextAllowedRefresh: [
            (s, p) => [p.query, s.response],
            (query, response): string | null => {
                return isInsightQueryNode(query) && response && 'next_allowed_client_refresh' in response
                    ? response.next_allowed_client_refresh
                    : null
            },
        ],
        getInsightRefreshButtonDisabledReason: [
            (s) => [s.nextAllowedRefresh, s.lastRefresh],
            (nextAllowedRefresh: string | null, lastRefresh: string | null) => (): string => {
                const now = dayjs()
                // Saved insights has a nextAllowedRefresh we use to check if the user can refresh again
                if (nextAllowedRefresh) {
                    const nextRefreshTime = dayjs(nextAllowedRefresh)
                    if (now.isBefore(nextRefreshTime)) {
                        return `You can refresh this insight again ${nextRefreshTime.from(now)}`
                    }
                }
                // For unsaved insights we check the last refresh time
                if (lastRefresh) {
                    const earliestRefresh = dayjs(lastRefresh).add(
                        UNSAVED_INSIGHT_MIN_REFRESH_INTERVAL_MINUTES,
                        'minutes'
                    )
                    if (now.isBefore(earliestRefresh)) {
                        return `You can refresh this insight again ${earliestRefresh.from(now)}`
                    }
                }
                // If we don't have a nextAllowedRefresh or lastRefresh, we can refresh, so we
                // return an empty string
                return ''
            },
        ],
        timings: [
            (s) => [s.response],
            (response): QueryTiming[] | null => {
                return response && 'timings' in response ? response.timings : null
            },
        ],
        numberOfRows: [
            (s) => [s.response],
            (response): number | null => {
                if (!response) {
                    return null
                }
                const fields = ['result', 'results']
                for (const field of fields) {
                    if (field in response && Array.isArray(response[field])) {
                        return response[field].length
                    }
                }
                return null
            },
        ],
    })),
    listeners(({ actions, values, cache, props }) => ({
        abortAnyRunningQuery: () => {
            if (cache.abortController) {
                cache.abortController.abort()
                cache.abortController = null
            }
        },
        abortQuery: async ({ queryId }) => {
            try {
                const { currentTeamId } = values
                await api.delete(`api/environments/${currentTeamId}/query/${queryId}/`)
            } catch (e) {
                console.warn('Failed cancelling query', e)
            }
        },
        cancelQuery: () => {
            actions.abortAnyRunningQuery()
            actions.resetLoadingTimer()
        },
        loadData: () => {
            actions.collectionNodeLoadData(props.key)
            actions.resetLoadingTimer()
        },
        loadDataSuccess: ({ response }) => {
            props.onData?.(response as Record<string, unknown> | null | undefined)
            actions.collectionNodeLoadDataSuccess(props.key)
            if ('query' in props.query) {
                cache.localResults[JSON.stringify(props.query.query)] = response
            }
        },
        loadDataFailure: () => {
            actions.collectionNodeLoadDataFailure(props.key)
        },
        loadNewDataSuccess: ({ response }) => {
            props.onData?.(response as Record<string, unknown> | null | undefined)
        },
        loadNextDataSuccess: ({ response }) => {
            props.onData?.(response as Record<string, unknown> | null | undefined)
        },
        resetLoadingTimer: () => {
            if (values.dataLoading) {
                const startTime = Date.now()
                cache.disposables.add(() => {
                    const timerId = window.setInterval(() => {
                        const seconds = Math.floor((Date.now() - startTime) / 1000)
                        actions.setLoadingTime(seconds)
                    }, 1000)
                    return () => window.clearInterval(timerId)
                }, 'loadingTimer')
            }
        },
    })),
    subscriptions(({ props, actions, values, cache }) => ({
        responseError: (error: string | null) => {
            props.onError?.(error)
        },
        autoLoadRunning: (autoLoadRunning) => {
            if (autoLoadRunning) {
                actions.loadNewData()
                cache.disposables.add(() => {
                    const timerId = window.setInterval(() => {
                        if (!values.responseLoading) {
                            actions.loadNewData()
                        }
                    }, AUTOLOAD_INTERVAL)
                    return () => window.clearInterval(timerId)
                }, 'autoLoadInterval')
            }
        },
        dataLoading: (dataLoading) => {
            if (!dataLoading) {
                // Clear loading timer when data loading finishes
                cache.disposables.dispose('loadingTimer')
            }
        },
    })),
    afterMount(({ actions, props, cache }) => {
        cache.localResults = {}
        if (props.cachedResults) {
            // Use cached results if available, otherwise this logic will load the data again.
            // We need to set them here, as the propsChanged listener will not trigger on mount
            // and if we never change the props, the cached results will never be used.
            actions.setResponse(props.cachedResults)
        } else if (props.autoLoad && Object.keys(props.query || {}).length > 0) {
            // Initial load should use non-force variant
            const refreshType = isInsightQueryNode(props.query) ? 'async' : 'blocking'
            actions.loadData(refreshType)
        }

        actions.mountDataNode(props.key, {
            id: props.key,
            loadData: actions.loadData,
            cancelQuery: actions.cancelQuery,
        })
    }),
    beforeUnmount(({ actions, props, values }) => {
        if (values.autoLoadRunning) {
            actions.stopAutoLoad()
        }
        if (values.dataLoading) {
            actions.abortAnyRunningQuery()
        }

        actions.unmountDataNode(props.key)
        // Disposables plugin handles timer cleanup automatically
    }),
])

const dedupeResults = (arr: any[], key: string): any[] => {
    return Object.values(
        arr.reduce((acc, item) => {
            acc[item[key]] = item
            return acc
        }, {})
    )
}
