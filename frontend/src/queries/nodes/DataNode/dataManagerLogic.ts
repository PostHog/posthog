import {
    kea,
    path,
    props,
    key,
    afterMount,
    selectors,
    propsChanged,
    reducers,
    actions,
    beforeUnmount,
    listeners,
    BuiltLogic,
} from 'kea'
import { loaders } from 'kea-loaders'
import { AnyDataNode } from '~/queries/schema'
import { dataNodeLogic } from './dataNodeLogic'
import { dataNodeLogicType } from './dataNodeLogicType'

type QueryId = string
type QueryStore = Record<QueryId, BuiltLogic<dataNodeLogicType>>
// {
//     queryObject: AnyDataNode
//     results: Record<string, Record<string, any>>
//     isLoading: boolean
// }

export const dataManagerLogic = kea([
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
    loaders(({ values }) => ({
        queries: {
            runQuery: ({ queryId, queryObject }: { queryId: QueryId; queryObject: AnyDataNode }): QueryStore => {
                const logic = dataNodeLogic.build({ key: queryId, query: queryObject })
                return { ...values.queries, [queryId]: logic }
            },
        },
    })),
    reducers({
        //     - queries: Record<queryId, Record>
        // - results: Record<queryId, any>
        // - lastUpdatedAt: Record<queryId, Date>
        // - isLoading: Record<queryId, bool>
    }),
    selectors({}),
])
