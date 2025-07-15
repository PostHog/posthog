import { lemonToast } from '@posthog/lemon-ui'
import { actions, kea, listeners, path, reducers } from 'kea'
import api from 'lib/api'

import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'

import type { personsSceneLogicType } from './personsSceneLogicType'

export const personsSceneLogic = kea<personsSceneLogicType>([
    path(['scenes', 'persons', 'personsSceneLogic']),

    actions({
        setQuery: (query: DataTableNode) => ({ query }),
        resetDeletedDistinctId: (distinct_id: string) => ({ distinct_id }),
    }),
    reducers({
        query: [
            {
                kind: NodeKind.DataTableNode,
                source: {
                    kind: NodeKind.ActorsQuery,
                    select: [...defaultDataTableColumns(NodeKind.ActorsQuery), 'person.$delete'],
                },
                full: true,
                propertiesViaUrl: true,
            } as DataTableNode,
            { setQuery: (_, { query }) => query },
        ],
    }),

    listeners({
        resetDeletedDistinctId: async ({ distinct_id }) => {
            await api.persons.resetPersonDistinctId(distinct_id)
            lemonToast.success('Distinct ID reset. It may take a few minutes to process.')
        },
    }),

    // NOTE: Temp disabled as it triggers a loop bug

    // actionToUrl(({ values }) => ({
    //     setQuery: () => [
    //         urls.persons(),
    //         {},
    //         objectsEqual(values.query, getDefaultQuery(values.queryFlagEnabled)) ? {} : { q: values.query },
    //         { replace: true },
    //     ],
    // })),

    // urlToAction(({ actions, values }) => ({
    //     [urls.persons()]: (_, __, { q: queryParam }): void => {
    //         if (!equal(queryParam, values.query)) {
    //             // nothing in the URL
    //             if (!queryParam) {
    //                 const defaultQuery = getDefaultQuery(values.queryFlagEnabled)
    //                 // set the default unless it's already there
    //                 if (!objectsEqual(values.query, defaultQuery)) {
    //                     actions.setQuery(defaultQuery)
    //                 }
    //             } else {
    //                 if (typeof queryParam === 'object') {
    //                     actions.setQuery(queryParam)
    //                 } else {
    //                     lemonToast.error('Invalid query in URL')
    //                     console.error({ queryParam })
    //                 }
    //             }
    //         }
    //     },
    // })),
])
