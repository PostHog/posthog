import { kea, path, props, key, afterMount, selectors, propsChanged, reducers, actions, beforeUnmount } from 'kea'
import { loaders } from 'kea-loaders'
import type { dataNodeLogicType } from './dataNodeLogicType'
import { DataNode, EventsNode } from '~/queries/schema'
import { query } from '~/queries/query'
import { isEventsNode, isEventsQuery, isPersonsNode } from '~/queries/utils'
import { subscriptions } from 'kea-subscriptions'
import { objectsEqual } from 'lib/utils'
import clsx from 'clsx'

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
        startAutoLoad: true,
        stopAutoLoad: true,
        toggleAutoLoad: true,
        highlightRows: (rowIds: string[], now = new Date().valueOf()) => ({ rowIds, now }),
    }),
    loaders(({ actions, values }) => ({
        response: [
            null as DataNode['response'] | null,
            {
                loadData: async () => {
                    return (await query<DataNode>(values.query)) ?? null
                },
                loadNewData: async () => {
                    if (!values.canLoadNewData || values.dataLoading) {
                        return values.response
                    }
                    const diffQuery: EventsNode =
                        values.response && values.response.results?.length > 0
                            ? {
                                  ...values.query,
                                  after: values.response.results[0].timestamp,
                              }
                            : values.query
                    const newResponse = (await query(diffQuery)) ?? null
                    actions.highlightRows((newResponse?.results ?? []).map((r) => r.id))
                    return {
                        results: [...(newResponse?.results ?? []), ...(values.response?.results ?? [])],
                        next: values.response?.next,
                    }
                },
                loadNextData: async () => {
                    if (!values.canLoadNextData || values.dataLoading) {
                        return values.response
                    }
                    const diffQuery: EventsNode =
                        values.response && values.response.results?.length > 0
                            ? {
                                  ...values.query,
                                  before: values.response.results[values.response.results.length - 1].timestamp,
                              }
                            : values.query
                    const newResponse = (await query(diffQuery)) ?? null
                    return {
                        results: [...(values.response?.results ?? []), ...(newResponse?.results ?? [])],
                        next: values.response?.next,
                    }
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
                    action: (isEventsNode(props.query) || isEventsQuery(props.query)) && props.query.actionId,
                    person: (isEventsNode(props.query) || isEventsQuery(props.query)) && props.query.personId,
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
        query: [() => [(_, props) => props.query], (query) => query],
        canLoadNewData: [
            (s) => [s.query],
            (query) => isEventsNode(query) || (isEventsQuery(query) && query.orderBy?.[0] === '-timestamp'),
        ],
        canLoadNextData: [
            (s) => [s.query, s.response],
            (query, response) => {
                return (
                    (isEventsNode(query) || isEventsQuery(query) || isPersonsNode(query)) &&
                    (response as EventsNode['response'])?.next &&
                    ((response as EventsNode['response'])?.results?.length ?? 0) > 0
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
