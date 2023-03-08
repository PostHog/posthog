import { actions, kea, path, reducers } from 'kea'

import type { eventsSceneLogicType } from './eventsSceneLogicType'
import { actionToUrl, urlToAction } from 'kea-router'
import equal from 'fast-deep-equal'
import { DataTableNode, Node, NodeKind } from '~/queries/schema'
import { urls } from 'scenes/urls'
import { objectsEqual } from 'lib/utils'
import { lemonToast } from 'lib/lemon-ui/lemonToast'
import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'

export const getDefaultEventsSceneQuery = (): DataTableNode => ({
    kind: NodeKind.DataTableNode,
    full: true,
    source: {
        kind: NodeKind.EventsQuery,
        select: defaultDataTableColumns(NodeKind.EventsQuery),
        orderBy: ['timestamp DESC'],
        after: '-24h',
        limit: 100,
    },
    propertiesViaUrl: true,
    showSavedQueries: true,
})

export const eventsSceneLogic = kea<eventsSceneLogicType>([
    path(['scenes', 'events', 'eventsSceneLogic']),

    actions({ setQuery: (query: Node) => ({ query }) }),
    reducers({ query: [getDefaultEventsSceneQuery() as Node, { setQuery: (_, { query }) => query }] }),

    actionToUrl(({ values }) => ({
        setQuery: () => [
            urls.events(),
            {},
            objectsEqual(values.query, getDefaultEventsSceneQuery()) ? {} : { q: values.query },
            { replace: true },
        ],
    })),

    urlToAction(({ actions, values }) => ({
        [urls.events()]: (_, __, { q: queryParam }): void => {
            if (!equal(queryParam, values.query)) {
                // nothing in the URL
                if (!queryParam) {
                    // set the default unless it's already there
                    if (!objectsEqual(values.query, getDefaultEventsSceneQuery())) {
                        actions.setQuery(getDefaultEventsSceneQuery())
                    }
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
