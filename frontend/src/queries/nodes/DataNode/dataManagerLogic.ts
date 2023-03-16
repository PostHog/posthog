import { kea, path, selectors, reducers, actions, defaults, BuiltLogic, listeners, connect } from 'kea'
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
    // connect({
    //     actions:
    // }),
    actions({
        runQuery: (queryId: QueryId, queryObject: AnyDataNode) => {
            console.log('runQuery: ', queryId, queryObject)
            const logic = dataNodeLogic.build({ key: queryId, query: queryObject })
            const unmount = logic.mount()
            return { queryId, queryObject, logic, unmount }
        },
        // cancelQuery: (queryId: QueryId) => ({ queryId }),
        // querySuccess: (queryId: QueryId, queryObject: AnyDataNode, results: Record<string, any>) => ({
        //     queryId,
        //     queryObject,
        //     results,
        // }),
        // queryFailure: (queryId: QueryId, error: Error) => ({ queryId, error }),
    }),
    // defaults({
    //     queries: {},
    // }),
    // loaders(({ values }) => ({
    //     queries: {
    //         runQuery: ({ queryId, queryObject }: { queryId: QueryId; queryObject: AnyDataNode }): QueryStore => {
    //             // console.log('V: ', values.queries)
    //             // console.log('queryId: ', queryId)
    //             // console.log('queryObject: ', queryObject)
    //             // const logic = dataNodeLogic.build({ key: queryId, query: queryObject })
    //             // console.log('logic: ', logic.values.responseLoading)
    //             // const queries = { ...values.queries, [queryId]: logic }
    //             // // console.log('queries: ', queries)
    //             // return queries
    //             // values.queries[queryId].actions.
    //         },
    //     },
    // })),
    reducers({
        queries: [
            {},
            {
                runQuery: (state, { queryId, queryObject, logic, unmount }) => {
                    return { ...state, [queryId]: { logic, unmount } }
                },
            },
        ],
        // - queries: Record<queryId, Record>
        // - results: Record<queryId, any>
        // - lastUpdatedAt: Record<queryId, Date>
        // - isLoading: Record<queryId, bool>
    }),
    selectors({
        // logic: [(s) => [s.queries], (queries: QueryStore) => (queryId: QueryId) => queries[queryId]?.logic],
        getQueryLoading: [
            (s) => [s.queries],
            (queries: QueryStore) => (queryId: QueryId) => {
                const logic = queries[queryId]?.logic
                return logic ? logic.values.responseLoading : null
            },
        ],
        getQueryResponse: [
            (s) => [s.queries],
            (queries: QueryStore) => (queryId: QueryId) => {
                const logic = queries[queryId]?.logic
                return logic ? logic.values.response : null
            },
        ],
        getQueryError: [
            (s) => [s.queries],
            (queries: QueryStore) => (queryId: QueryId) => {
                const logic = queries[queryId]?.logic
                return logic ? logic.values.responseError : null
            },
        ],
    }),
    // listeners({}),
])
