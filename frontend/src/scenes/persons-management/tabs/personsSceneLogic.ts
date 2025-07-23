import { lemonToast } from '@posthog/lemon-ui'
import { actions, kea, listeners, path, reducers } from 'kea'
import api from 'lib/api'

import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { DataTableNode, NodeKind, ActorsQuery } from '~/queries/schema/schema-general'
import { permanentlyMount } from 'lib/utils/kea-logic-builders'

import type { personsSceneLogicType } from './personsSceneLogicType'
import { actionToUrl, urlToAction, router } from 'kea-router'
import { urls } from 'scenes/urls'

type ChangeUrlOutput = [
    string,
    Record<string, any>,
    Record<string, any>,
    {
        replace: boolean
    }
]

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

    actionToUrl(({ values }) => {
        const changeUrl = (): ChangeUrlOutput | void => {
            const { currentLocation } = router.values
            const defaultUrl: ChangeUrlOutput = [
                currentLocation.pathname,
                currentLocation.searchParams,
                currentLocation.hashParams,
                { replace: false },
            ]
            if (values.query.source.kind !== NodeKind.ActorsQuery) {
                return defaultUrl
            }
            const searchTerm = values.query.source.search
            if (searchTerm == null) {
                return defaultUrl
            }
            const newUrl: ChangeUrlOutput = [
                currentLocation.pathname,
                { ...currentLocation.searchParams, search: searchTerm },
                currentLocation.hashParams,
                { replace: false },
            ]
            return newUrl
        }

        return {
            setQuery: changeUrl,
        }
    }),

    urlToAction(({ actions, values }) => ({
        [urls.persons()]: async (_, searchParams) => {
            const searchInUrl = searchParams['search']
            if (values.query.source.kind !== NodeKind.ActorsQuery) {
                return
            }
            const newSearch = searchInUrl ?? values.query.source.search
            const newSource: ActorsQuery = {
                ...values.query.source,
                search: newSearch,
            }
            actions.setQuery({
                ...values.query,
                source: newSource,
            })
        },
    })),

    permanentlyMount(),

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
