import equal from 'fast-deep-equal'
import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { actionToUrl, urlToAction } from 'kea-router'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { objectsEqual } from 'lib/utils'
import { getDefaultLiveEventsSceneQuery } from 'scenes/events-management/live-events/defaults'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Node } from '~/queries/schema'

import type { liveEventsSceneLogicType } from './liveEventsSceneLogicType'

export const liveEventsSceneLogic = kea<liveEventsSceneLogicType>([
    path(['scenes', 'events', 'liveEventsSceneLogic']),
    connect({ values: [teamLogic, ['currentTeam']] }),

    actions({ setQuery: (query: Node) => ({ query }) }),
    reducers({ savedQuery: [null as Node | null, { setQuery: (_, { query }) => query }] }),
    selectors({
        defaultQuery: [
            () => [],
            () => {
                return getDefaultLiveEventsSceneQuery()
            },
        ],
        query: [(s) => [s.savedQuery, s.defaultQuery], (savedQuery, defaultQuery) => savedQuery || defaultQuery],
    }),
    actionToUrl(({ values }) => ({
        setQuery: () => [
            urls.events(),
            {},
            objectsEqual(values.query, values.defaultQuery) ? {} : { q: values.query },
            { replace: true },
        ],
    })),

    urlToAction(({ actions, values }) => ({
        [urls.events()]: (_, __, { q: queryParam }): void => {
            if (!equal(queryParam, values.query)) {
                // nothing in the URL
                if (!queryParam) {
                    // set the default unless it's already there
                    if (!objectsEqual(values.query, values.defaultQuery)) {
                        actions.setQuery(values.defaultQuery)
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
