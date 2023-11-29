import { actions, afterMount, connect, kea, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { objectsEqual, shouldCancelQuery, uuid } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'

import { query } from '~/queries/query'
import { AnyResponseType, DataVisualizationNode } from '~/queries/schema'

import { dataVisualizationLogicType } from './dataVisualizationLogicType'

export interface DataVisualizationLogicProps {
    key: string
    query: DataVisualizationNode
    cachedResults?: AnyResponseType
}

export const dataVisualizationLogic = kea<dataVisualizationLogicType>([
    path(['queries', 'nodes', 'DataVisualization', 'dataVisualizationLogic']),
    connect({
        values: [teamLogic, ['currentTeamId']],
    }),
    props({ query: {} } as DataVisualizationLogicProps),
    propsChanged(({ actions, props }, oldProps) => {
        if (!props.query) {
            return // Can't do anything without a query
        }
        if (oldProps.query && props.query.kind !== oldProps.query.kind) {
            actions.clearResponse()
        }
        if (!objectsEqual(props.query, oldProps.query)) {
            if (!props.cachedResults || (!props.cachedResults['result'] && !props.cachedResults['results'])) {
                actions.loadData()
            } else {
                actions.setResponse(props.cachedResults)
            }
        }
    }),
    actions({
        loadData: (refresh = false) => ({ refresh, queryId: uuid() }),
        setResponse: (response: Exclude<AnyResponseType, undefined>) => response,
        clearResponse: true,
        abortQuery: (payload: { queryId: string }) => payload,
    }),
    loaders(({ props, actions, cache }) => ({
        response: [
            props.cachedResults ?? null,
            {
                setResponse: (response) => response,
                clearResponse: () => null,
                loadData: async ({ refresh, queryId }, breakpoint) => {
                    try {
                        cache.abortController = new AbortController()
                        const data =
                            (await query<DataVisualizationNode>(
                                props.query,
                                { signal: cache.abortController.signal },
                                refresh,
                                queryId
                            )) ?? null
                        breakpoint()
                        return data
                    } catch (e: any) {
                        if (shouldCancelQuery(e)) {
                            actions.abortQuery({ queryId })
                        }
                        breakpoint()
                        e.queryId = queryId
                        throw e
                    }
                },
            },
        ],
    })),
    reducers({
        columns: [
            [] as { name: string; type: string }[],
            {
                loadDataSuccess: (_state, { response }) => {
                    if (!response) {
                        return []
                    }

                    const columns: string[] = response['columns']
                    const types: string[][] = response['types']

                    return columns.map((column, index) => {
                        const type = types[index][1]
                        return {
                            name: column,
                            type,
                        }
                    })
                },
            },
        ],
    }),
    selectors({
        query: [(_state, props) => [props.query], (query) => query],
    }),
    listeners(({ values }) => ({
        abortQuery: async ({ queryId }) => {
            try {
                const { currentTeamId } = values
                await api.delete(`api/projects/${currentTeamId}/query/${queryId}/`)
            } catch (e) {
                console.warn('Failed cancelling query', e)
            }
        },
    })),
    afterMount(({ actions, props }) => {
        if (Object.keys(props.query || {}).length > 0) {
            actions.loadData()
        }
    }),
])
