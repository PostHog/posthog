import { kea, path, selectors, reducers, actions, defaults, BuiltLogic } from 'kea'
import { loaders } from 'kea-loaders'
import { AnyDataNode } from '~/queries/schema'
import { dataNodeLogic } from './dataNodeLogic'
import { dataNodeLogicType } from './dataNodeLogicType'

import type { dataManagerLogicType } from './dataManagerLogicType'

export type QueryId = string
export type QueryStore = Record<QueryId, BuiltLogic<dataNodeLogicType>>
// {
//     queryObject: AnyDataNode
//     results: Record<string, Record<string, any>>
//     isLoading: boolean
// }

export const dataManagerLogic = kea<dataManagerLogicType>([
    path(['queries', 'nodes', 'dataManagerLogic']),
    actions({
        // runQuery: (queryId: QueryId, queryObject: AnyDataNode) => ({ queryId, queryObject }),
        // cancelQuery: (queryId: QueryId) => ({ queryId }),
        // querySuccess: (queryId: QueryId, queryObject: AnyDataNode, results: Record<string, any>) => ({
        //     queryId,
        //     queryObject,
        //     results,
        // }),
        // queryFailure: (queryId: QueryId, error: Error) => ({ queryId, error }),
    }),
    defaults({
        queries: {},
    }),
    loaders(({ values }) => ({
        queries: {
            runQuery: ({ queryId, queryObject }: { queryId: QueryId; queryObject: AnyDataNode }): QueryStore => {
                // console.log('V: ', values.queries)
                // console.log('queryId: ', queryId)
                // console.log('queryObject: ', queryObject)
                // const logic = dataNodeLogic.build({ key: queryId, query: queryObject })
                // console.log('logic: ', logic.values.responseLoading)
                // const queries = { ...values.queries, [queryId]: logic }
                // // console.log('queries: ', queries)
                // return queries
                // values.queries[queryId].actions.
            },
        },
    })),
    reducers({
        queries: {
            runQuery: (state, { queryId, queryObject }) => {
                const logic = dataNodeLogic.build({ key: queryId, query: queryObject })
                return { ...state, [queryId]: logic }
            },
        },
        //     - queries: Record<queryId, Record>
        // - results: Record<queryId, any>
        // - lastUpdatedAt: Record<queryId, Date>
        // - isLoading: Record<queryId, bool>
    }),
    selectors({
        isLoading: [
            (s) => [s.queries],
            (queries: QueryStore) => (queryId: QueryId) => {
                const logic = queries[queryId]
                return logic ? logic.values.responseLoading : null
            },
        ],
    }),
])
