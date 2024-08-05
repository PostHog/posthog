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
import { dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { objectsEqual, shouldCancelQuery, uuid } from 'lib/utils'
import { ConcurrencyController } from 'lib/utils/concurrencyController'
import { UNSAVED_INSIGHT_MIN_REFRESH_INTERVAL_MINUTES } from 'scenes/insights/insightLogic'
import { compareInsightQuery } from 'scenes/insights/utils/compareInsightQuery'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { dataNodeCollectionLogic, DataNodeCollectionProps } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { removeExpressionComment } from '~/queries/nodes/DataTable/utils'
import { performQuery } from '~/queries/query'
import { QueryStatus } from '~/queries/schema'
import {
    ActorsQuery,
    ActorsQueryResponse,
    AnyResponseType,
    DataNode,
    EventsQuery,
    EventsQueryResponse,
    HogQLQueryModifiers,
    InsightVizNode,
    NodeKind,
    PersonsNode,
    QueryTiming,
} from '~/queries/schema'
import {
    isActorsQuery,
    isEventsQuery,
    isFunnelsQuery,
    isInsightActorsQuery,
    isInsightQueryNode,
    isPersonsNode,
} from '~/queries/utils'

import type { dataNodeLogicType } from './dataNodeLogicType'

export interface DataNodeLogicProps {
    key: string
    query: DataNode
    /** Cached results when fetching nodes in bulk (list endpoint), sharing or exporting. */
    cachedResults?: AnyResponseType
    /** Disabled data fetching and only allow cached results. */
    doNotLoad?: boolean
    /** Queries always get refreshed. */
    alwaysRefresh?: boolean
    /** Callback when data is successfully loader or provided from cache. */
    onData?: (data: Record<string, unknown> | null | undefined) => void
    /** Load priority. Higher priority (smaller number) queries will be loaded first. */
    loadPriority?: number
    /** Override modifiers when making the request */
    modifiers?: HogQLQueryModifiers

    dataNodeCollectionId?: string
}

export const AUTOLOAD_INTERVAL = 30000
const LOAD_MORE_ROWS_LIMIT = 10000

const concurrencyController = new ConcurrencyController(1)

/** Compares two queries for semantic equality to prevent double-fetching of data. */
const queryEqual = (a: DataNode, b: DataNode): boolean => {
    if (isInsightQueryNode(a) && isInsightQueryNode(b)) {
        return compareInsightQuery(a, b, true)
    }
    return objectsEqual(a, b)
}

/** Tests wether a query is valid to prevent unnecessary requests.  */
const queryValid = (q: DataNode): boolean => {
    if (isFunnelsQuery(q)) {
        // funnels require at least two steps
        return q.series.length >= 2
    }
    return true
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

export const dataNodeLogic = kea<dataNodeLogicType>([
    path(['queries', 'nodes', 'dataNodeLogic']),
    key((props) => props.key),
    connect((props: DataNodeLogicProps) => ({
        values: [userLogic, ['user'], teamLogic, ['currentTeamId'], featureFlagLogic, ['featureFlags']],
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
    props({ query: {} } as DataNodeLogicProps),
    propsChanged(({ actions, props }, oldProps) => {
        if (!props.query) {
            return // Can't do anything without a query
        }
        if (oldProps.query?.kind && props.query.kind !== oldProps.query.kind) {
            actions.clearResponse()
        }
        const hasQueryChanged = !queryEqual(props.query, oldProps.query)
        const queryStatus = (props.cachedResults?.query_status || null) as QueryStatus | null
        if (hasQueryChanged && queryStatus?.complete === false) {
            // If there is an incomplete query, load the data with the same query_id which should return its status
            actions.loadData(undefined, queryStatus.id)
        } else if (
            hasQueryChanged &&
            !(props.cachedResults && props.key.includes('dashboard')) && // Don't load data on dashboard if cached results are available
            (!props.cachedResults ||
                (isInsightQueryNode(props.query) && !props.cachedResults['result'] && !props.cachedResults['results']))
        ) {
            actions.loadData()
        } else if (props.cachedResults) {
            // Use cached results if available, otherwise this logic will load the data again
            actions.setResponse(props.cachedResults)
        }
    }),
    actions({
        loadData: (refresh = false, queryId?: string) => ({ refresh, queryId: queryId || uuid() }),
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
    }),
    loaders(({ actions, cache, values, props }) => ({
        response: [
            props.cachedResults ?? null,
            {
                setResponse: (response) => response,
                clearResponse: () => null,
                loadData: async ({ refresh: refreshArg, queryId }, breakpoint) => {
                    const refresh = props.alwaysRefresh || refreshArg
                    if (props.doNotLoad) {
                        return props.cachedResults
                    }

                    const queryStatus = (props.cachedResults?.query_status || null) as QueryStatus | null
                    if (props.cachedResults && !refresh && queryStatus?.complete !== false) {
                        if (props.cachedResults['result'] || props.cachedResults['results']) {
                            return props.cachedResults
                        }
                    }

                    if (!values.currentTeamId) {
                        // if shared/exported, the team is not loaded
                        return null
                    }

                    if (props.query === undefined || Object.keys(props.query).length === 0) {
                        // no need to try and load a query before properly initialized
                        return null
                    }

                    if (!queryValid(props.query)) {
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
                        const response = await concurrencyController.run({
                            debugTag: props.query.kind,
                            abortController,
                            priority: props.loadPriority,
                            fn: async (): Promise<{ duration: number; data: Record<string, any> }> => {
                                const now = performance.now()
                                try {
                                    breakpoint()
                                    const data =
                                        (await performQuery<DataNode>(
                                            addModifiers(props.query, props.modifiers),
                                            methodOptions,
                                            refresh,
                                            queryId,
                                            actions.setPollResponse
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
                                props.alwaysRefresh
                            )) ?? null
                        actions.setElapsedTime(performance.now() - now)
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
                    if (isEventsQuery(props.query) || isActorsQuery(props.query)) {
                        const newResponse =
                            (await performQuery(
                                addModifiers(values.nextQuery, props.modifiers),
                                undefined,
                                props.alwaysRefresh
                            )) ?? null
                        actions.setElapsedTime(performance.now() - now)
                        const queryResponse = values.response as EventsQueryResponse | ActorsQueryResponse
                        return {
                            ...queryResponse,
                            results: [...(queryResponse?.results ?? []), ...(newResponse?.results ?? [])],
                            hasMore: newResponse?.hasMore,
                        }
                    } else if (isPersonsNode(props.query)) {
                        const newResponse =
                            (await performQuery(
                                addModifiers(values.nextQuery, props.modifiers),
                                undefined,
                                props.alwaysRefresh
                            )) ?? null
                        actions.setElapsedTime(performance.now() - now)
                        if (Array.isArray(values.response)) {
                            // help typescript by asserting we can't have an array here
                            throw new Error('Unexpected response type for persons node query')
                        }
                        return {
                            ...values.response,
                            results: [...(values.response?.results ?? []), ...(newResponse?.results ?? [])],
                            next: newResponse?.next,
                        }
                    }
                    return values.response
                },
            },
        ],
    })),
    reducers(({ props }) => ({
        dataLoading: [
            false,
            {
                loadData: () => true,
                loadDataSuccess: () => false,
                loadDataFailure: () => false,
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
            },
        ],
        nextDataLoading: [
            false,
            {
                loadNextData: () => true,
                loadNextDataSuccess: () => false,
                loadNextDataFailure: () => false,
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
                loadDataFailure: (_, { error, errorObject }) => {
                    if (errorObject && 'error' in errorObject) {
                        return errorObject.error ?? 'Error loading data'
                    }
                    if (errorObject && 'detail' in errorObject) {
                        return errorObject.detail ?? 'Error loading data'
                    }
                    return error ?? 'Error loading data'
                },
                loadDataSuccess: (_, { response }) => response?.error ?? null,
            },
        ],
        elapsedTime: [
            null as number | null,
            {
                setElapsedTime: (_, { elapsedTime }) => elapsedTime,
                loadData: () => null,
                loadNewData: () => null,
                loadNextData: () => null,
            },
        ],
    })),
    selectors({
        isShowingCachedResults: [
            () => [(_, props) => props.cachedResults ?? null],
            (cachedResults: AnyResponseType | null): boolean => !!cachedResults,
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
            (s, p) => [p.query, s.response, s.responseError, s.dataLoading, s.isShowingCachedResults],
            (query, response, responseError, dataLoading, isShowingCachedResults): DataNode | null => {
                if (isShowingCachedResults) {
                    return null
                }

                if ((isEventsQuery(query) || isActorsQuery(query)) && !responseError && !dataLoading) {
                    if ((response as EventsQueryResponse | ActorsQueryResponse)?.hasMore) {
                        const sortKey = query.orderBy?.[0] ?? 'timestamp DESC'
                        const typedResults = (response as EventsQueryResponse | ActorsQueryResponse)?.results
                        if (isEventsQuery(query) && sortKey === 'timestamp DESC') {
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
                                            Math.min(2 * (typedResults?.length || 100), LOAD_MORE_ROWS_LIMIT)
                                        ),
                                    }
                                    return newQuery
                                }
                            }
                        } else {
                            return {
                                ...query,
                                offset: typedResults?.length || 0,
                                limit: Math.max(100, Math.min(2 * (typedResults?.length || 100), LOAD_MORE_ROWS_LIMIT)),
                            } as EventsQuery | ActorsQuery
                        }
                    }
                }
                if (isPersonsNode(query) && response && !responseError && response.next) {
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
                if (!response?.hasMore) {
                    return false
                }
                return response.hasMore
            },
        ],
        dataLimit: [
            // get limit from response
            (s) => [s.response],
            (response): number | null => {
                if (!response?.limit) {
                    return null
                }
                return response.limit
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
                let disabledReason = ''
                if (!!nextAllowedRefresh && now.isBefore(dayjs(nextAllowedRefresh))) {
                    // If this is a saved insight, the result will contain nextAllowedRefresh, and we use that to disable the button
                    disabledReason = `You can refresh this insight again ${dayjs(nextAllowedRefresh).from(now)}`
                } else if (
                    !!lastRefresh &&
                    now.subtract(UNSAVED_INSIGHT_MIN_REFRESH_INTERVAL_MINUTES - 0.5, 'minutes').isBefore(lastRefresh)
                ) {
                    // Unsaved insights don't get cached and get refreshed on every page load, but we avoid allowing users to click
                    // 'refresh' more than once every UNSAVED_INSIGHT_MIN_REFRESH_INTERVAL_MINUTES. This can be bypassed by simply
                    // refreshing the page though, as there's no cache layer on the backend
                    disabledReason = `You can refresh this insight again ${dayjs(lastRefresh)
                        .add(UNSAVED_INSIGHT_MIN_REFRESH_INTERVAL_MINUTES, 'minutes')
                        .from(now)}`
                }

                return disabledReason
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
    }),
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
                await api.delete(`api/projects/${currentTeamId}/query/${queryId}/`)
            } catch (e) {
                console.warn('Failed cancelling query', e)
            }
        },
        cancelQuery: () => {
            actions.abortAnyRunningQuery()
        },
        loadData: () => {
            actions.collectionNodeLoadData(props.key)
        },
        loadDataSuccess: ({ response }) => {
            props.onData?.(response)
            actions.collectionNodeLoadDataSuccess(props.key)
        },
        loadDataFailure: () => {
            actions.collectionNodeLoadDataFailure(props.key)
        },
        loadNewDataSuccess: ({ response }) => {
            props.onData?.(response)
        },
        loadNextDataSuccess: ({ response }) => {
            props.onData?.(response)
        },
    })),
    subscriptions(({ actions, cache, values }) => ({
        autoLoadRunning: (autoLoadRunning) => {
            if (cache.autoLoadInterval) {
                window.clearInterval(cache.autoLoadInterval)
                cache.autoLoadInterval = null
            }
            if (autoLoadRunning) {
                actions.loadNewData()
                cache.autoLoadInterval = window.setInterval(() => {
                    if (!values.responseLoading) {
                        actions.loadNewData()
                    }
                }, AUTOLOAD_INTERVAL)
            }
        },
    })),
    afterMount(({ actions, props }) => {
        if (props.cachedResults) {
            // Use cached results if available, otherwise this logic will load the data again.
            // We need to set them here, as the propsChanged listener will not trigger on mount
            // and if we never change the props, the cached results will never be used.
            actions.setResponse(props.cachedResults)
        } else if (Object.keys(props.query || {}).length > 0) {
            actions.loadData()
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
    }),
])
