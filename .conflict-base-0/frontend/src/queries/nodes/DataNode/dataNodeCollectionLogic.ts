import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { RefreshType } from '~/queries/schema/schema-general'

import type { dataNodeCollectionLogicType } from './dataNodeCollectionLogicType'

export interface DataNodeRegisteredProps {
    id: string
    loadData: (refresh?: RefreshType) => void
    cancelQuery: () => void
}

export interface DataNodeCollectionProps {
    key: string
}

export interface DataNodeStatus {
    isLoading: boolean
    hasError: boolean
}

export type DataNodeStatusMap = Record<string, DataNodeStatus | undefined>

export const dataNodeCollectionLogic = kea<dataNodeCollectionLogicType>([
    path(['queries', 'nodes', 'dataNodeCollectionLogic']),
    props({} as DataNodeCollectionProps),
    key((props: DataNodeCollectionProps) => {
        return props.key
    }),
    actions({
        mountDataNode: (id: string, props: DataNodeRegisteredProps) => ({ id, props }),
        unmountDataNode: (id: string) => ({ id }),
        reloadAll: () => ({}),
        cancelAllLoading: () => ({}),
        collectionNodeLoadData: (id: string) => ({ id }),
        collectionNodeLoadDataSuccess: (id: string) => ({ id }),
        collectionNodeLoadDataFailure: (id: string) => ({ id }),
    }),
    reducers({
        mountedDataNodes: [
            [] as DataNodeRegisteredProps[],
            {
                mountDataNode: (state, payload) => {
                    const filtered = state.filter((node) => node.id !== payload.id)
                    return [...filtered, payload.props]
                },
                unmountDataNode: (state, payload) => state.filter((node) => node.id !== payload.id),
            },
        ],
        collectionNodeStatus: [
            {} as DataNodeStatusMap,
            {
                mountDataNode: (state, payload) => {
                    return { ...state, [payload.id]: { isLoading: false, hasError: false } }
                },
                unmountDataNode: (state, payload) => {
                    const { [payload.id]: _discard, ...rest } = state
                    return rest
                },
                collectionNodeLoadData: (state, payload) => {
                    return { ...state, [payload.id]: { isLoading: true, hasError: false } }
                },
                collectionNodeLoadDataSuccess: (state, payload) => {
                    return { ...state, [payload.id]: { isLoading: false, hasError: false } }
                },
                collectionNodeLoadDataFailure: (state, payload) => {
                    return { ...state, [payload.id]: { isLoading: false, hasError: true } }
                },
            },
        ],
    }),
    selectors({
        areAnyLoading: [
            (s) => [s.collectionNodeStatus],
            (collectionNodeStatus: DataNodeStatusMap) => {
                return Object.values(collectionNodeStatus).some((status) => {
                    return status?.isLoading
                })
            },
        ],
    }),
    listeners(({ values }) => ({
        reloadAll: () => {
            // We want to force refresh all nodes, so we use 'force_async' to bypass cache
            // The loadData function in each node will handle converting this to the appropriate type
            // based on whether the node is an insight or not
            values.mountedDataNodes.forEach((node) => node.loadData('force_async'))
        },
        cancelAllLoading: () => {
            values.mountedDataNodes.forEach((node) => {
                const status = values.collectionNodeStatus[node.id]
                if (status?.isLoading) {
                    node.cancelQuery()
                }
            })
        },
    })),
])
