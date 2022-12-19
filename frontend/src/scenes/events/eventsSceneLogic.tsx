import { actions, kea, path, reducers } from 'kea'

import type { eventsSceneLogicType } from './eventsSceneLogicType'
import { actionToUrl, urlToAction } from 'kea-router'
import equal from 'fast-deep-equal'
import { DataTableNode, Node, NodeKind } from '~/queries/schema'
import { urls } from 'scenes/urls'
import { objectsEqual } from 'lib/utils'
import { lemonToast } from 'lib/components/lemonToast'

const getDefaultQuery = (): DataTableNode => ({
    kind: NodeKind.DataTableNode,
    source: {
        kind: NodeKind.EventsQuery,
        select: [
            '*',
            'event',
            'person',
            'coalesce(properties.$current_url, properties.$screen_name) # Url / Screen',
            'properties.$lib',
            'timestamp',
        ],
        orderBy: ['-timestamp'],
        limit: 100,
    },
    hiddenColumns: ['*'],
    propertiesViaUrl: true,
    showEventsBufferWarning: true,
    showColumnConfigurator: true,
    showEventFilter: true,
    showExport: true,
    showPropertyFilter: true,
    showReload: true,
    allowSorting: false,
})

export const eventsSceneLogic = kea<eventsSceneLogicType>([
    path(['scenes', 'events', 'eventsSceneLogic']),

    actions({ setQuery: (query: Node) => ({ query }) }),
    reducers({ query: [getDefaultQuery() as Node, { setQuery: (_, { query }) => query }] }),

    actionToUrl(({ values }) => ({
        setQuery: () => [
            urls.events(),
            {},
            objectsEqual(values.query, getDefaultQuery()) ? {} : { q: values.query },
            { replace: true },
        ],
    })),

    urlToAction(({ actions, values }) => ({
        [urls.events()]: (_, __, { q: queryParam }): void => {
            if (!equal(queryParam, values.query)) {
                // nothing in the URL
                if (!queryParam) {
                    // set the default unless it's already there
                    if (!objectsEqual(values.query, getDefaultQuery())) {
                        actions.setQuery(getDefaultQuery())
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
