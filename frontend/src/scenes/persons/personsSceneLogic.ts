import { lemonToast } from '@posthog/lemon-ui'
import { actions, kea, listeners, path, reducers } from 'kea'
import api from 'lib/api'

import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'

import type { personsSceneLogicType } from './personsSceneLogicType'
import { urls } from 'scenes/urls'
import equal from 'fast-deep-equal'
import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { tabAwareActionToUrl } from 'lib/logic/scenes/tabAwareActionToUrl'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'

const defaultQuery = {
    kind: NodeKind.DataTableNode,
    source: {
        kind: NodeKind.ActorsQuery,
        select: [...defaultDataTableColumns(NodeKind.ActorsQuery), 'person.$delete'],
    },
    full: true,
    propertiesViaUrl: true,
} as DataTableNode

export const personsSceneLogic = kea<personsSceneLogicType>([
    path(['scenes', 'persons', 'personsSceneLogic']),
    tabAwareScene(),

    actions({
        setQuery: (query: DataTableNode) => ({ query }),
        resetDeletedDistinctId: (distinct_id: string) => ({ distinct_id }),
    }),

    reducers({
        query: [defaultQuery, { setQuery: (_, { query }) => query }],
    }),

    listeners({
        resetDeletedDistinctId: async ({ distinct_id }) => {
            await api.persons.resetPersonDistinctId(distinct_id)
            lemonToast.success('Distinct ID reset. It may take a few minutes to process.')
        },
    }),

    tabAwareActionToUrl(({ values }) => ({
        setQuery: () => [
            urls.persons(),
            {},
            equal(values.query, defaultQuery) ? {} : { q: values.query },
            { replace: true },
        ],
    })),

    tabAwareUrlToAction(({ actions, values }) => ({
        [urls.persons()]: (_, __, { q: queryParam }): void => {
            if (!equal(queryParam, values.query)) {
                // nothing in the URL
                if (!queryParam) {
                    // We set the query again so that the actionToUrl for setQuery can run, which updates the url
                    actions.setQuery(values.query)
                } else {
                    if (typeof queryParam === 'object') {
                        actions.setQuery(queryParam)
                    } else {
                        lemonToast.error('Invalid query in URL')
                        console.error({ queryParam })
                    }
                }
            }
        },
    })),
])
