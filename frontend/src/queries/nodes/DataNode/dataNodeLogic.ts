import { kea, path, props, key, afterMount, selectors, propsChanged, reducers, actions, beforeUnmount } from 'kea'
import { loaders } from 'kea-loaders'
import type { dataNodeLogicType } from './dataNodeLogicType'
import { DataNode, EventsQuery, PersonsNode } from '~/queries/schema'
import { query } from '~/queries/query'
import { isEventsQuery, isPersonsNode } from '~/queries/utils'
import { subscriptions } from 'kea-subscriptions'
import { objectsEqual } from 'lib/utils'
import clsx from 'clsx'
import { getNextQuery } from '~/queries/nodes/DataNode/utils'

export interface DataNodeLogicProps {
    key: string
    query: DataNode
}

const AUTOLOAD_INTERVAL = 5000

export const dataNodeLogic = kea<dataNodeLogicType>([
    path(['queries', 'nodes', 'dataNodeLogic']),
    props({} as DataNodeLogicProps),
    key((props) => props.key),
    propsChanged(({ actions, props }, oldProps) => {
        if (!objectsEqual(props.query, oldProps.query)) {
            actions.loadData()
        }
    }),
    actions({
        loadData: true,
        startAutoLoad: true,
        stopAutoLoad: true,
        toggleAutoLoad: true,
        highlightRows: (rowIds: string[], now = new Date().valueOf()) => ({ rowIds, now }),
    }),
    loaders(({ values, props }) => ({
        response: [
            null as DataNode['response'] | null,
            {
                loadData: async (_, breakpoint) => {
                    const data = (await query<DataNode>(props.query)) ?? null
                    breakpoint()
                    return data
                },
                loadNewData: async () => {
                    if (!values.canLoadNewData || values.dataLoading) {
                        return values.response
                    }
                    if (isEventsQuery(props.query)) {
                        const diffQuery: EventsQuery =
                            values.response && values.response.results?.length > 0
                                ? {
                                      ...props.query,
                                      after: values.response.results[0].timestamp,
                                  }
                                : props.query
                        const newResponse = (await query(diffQuery)) ?? null
                        // TODO: get this back
                        // actions.highlightRows((newResponse?.results ?? []).map((r) => r.id))
                        return {
                            results: [...(newResponse?.results ?? []), ...(values.response?.results ?? [])],
                            next: values.response?.next,
                        }
                    }
                    return values.response
                },
                loadNextData: async () => {
                    if (!values.canLoadNextData || values.dataLoading) {
                        return values.response
                    }
                    if (isEventsQuery(props.query) && values.nextQuery) {
                        const newResponse = (await query(values.nextQuery)) ?? null
                        return {
                            results: [...(values.response?.results ?? []), ...(newResponse?.results ?? [])],
                            hasMore: newResponse?.hasMore,
                        }
                    }
                    return values.response
                },
            },
        ],
    })),
    reducers(({ props }) => ({
        dataLoading: [false, { loadData: () => true, loadDataSuccess: () => false, loadDataFailure: () => false }],
        newDataLoading: [
            false,
            { loadNewData: () => true, loadNewDataSuccess: () => false, loadNewDataFailure: () => false },
        ],
        nextDataLoading: [
            false,
            { loadNextData: () => true, loadNextDataSuccess: () => false, loadNextDataFailure: () => false },
        ],
        autoLoadToggled: [
            false,
            // store the autoload toggle's state in localstorage, separately for each data node kind
            {
                persist: true,
                storageKey: clsx('queries.nodes.dataNodeLogic.autoLoadToggled', props.query.kind, {
                    action: isEventsQuery(props.query) && props.query.actionId,
                    person: isEventsQuery(props.query) && props.query.personId,
                }),
            },
            { toggleAutoLoad: (state) => !state },
        ],
        autoLoadStarted: [false, { startAutoLoad: () => true, stopAutoLoad: () => false }],
        highlightedRows: [
            {} as Record<string, number>,
            {
                highlightRows: (state, { rowIds, now }) => {
                    const newState = { ...state }
                    for (const rowId of rowIds) {
                        newState[rowId] = now
                    }
                    return newState
                },
                loadDataSuccess: () => ({}),
            },
        ],
    })),
    selectors({
        canLoadNewData: [
            (_, p) => [p.query],
            (query) => isEventsQuery(query) && query.orderBy?.length === 1 && query.orderBy?.[0] === '-timestamp',
        ],
        nextQuery: [
            (s, p) => [p.query, s.response],
            (query, response): DataNode | null => {
                return isEventsQuery(query) && (response as EventsQuery['response'])?.hasMore
                    ? getNextQuery({ ...query, response: response as EventsQuery['response'] })
                    : null
            },
        ],
        canLoadNextData: [
            (s, p) => [p.query, s.response, s.nextQuery],
            (query, response, nextQuery) => {
                return (
                    (isPersonsNode(query) &&
                        (response as PersonsNode['response'])?.next &&
                        ((response as PersonsNode['response'])?.results?.length ?? 0) > 0) ||
                    (isEventsQuery(query) && !!nextQuery)
                )
            },
        ],
        autoLoadRunning: [
            (s) => [s.autoLoadToggled, s.autoLoadStarted, s.dataLoading],
            (autoLoadToggled, autoLoadStarted, dataLoading) => autoLoadToggled && autoLoadStarted && !dataLoading,
        ],
    }),
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
    afterMount(({ actions }) => {
        actions.loadData()
    }),
    beforeUnmount(({ actions, values }) => {
        if (values.autoLoadRunning) {
            actions.stopAutoLoad()
        }
    }),
])
