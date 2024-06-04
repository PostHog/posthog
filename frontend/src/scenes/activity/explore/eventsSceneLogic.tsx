import equal from 'fast-deep-equal'
import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { actionToUrl, urlToAction } from 'kea-router'
import { UrlToActionPayload } from 'kea-router/lib/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { objectsEqual } from 'lib/utils'
import { getDefaultEventsSceneQuery } from 'scenes/activity/explore/defaults'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { getDefaultEventsQueryForTeam } from '~/queries/nodes/DataTable/defaultEventsQuery'
import { Node } from '~/queries/schema'
import { ActivityTab } from '~/types'

import type { eventsSceneLogicType } from './eventsSceneLogicType'

export const eventsSceneLogic = kea<eventsSceneLogicType>([
    path(['scenes', 'events', 'eventsSceneLogic']),
    connect({ values: [teamLogic, ['currentTeam'], featureFlagLogic, ['featureFlags']] }),

    actions({ setQuery: (query: Node) => ({ query }) }),
    reducers({ savedQuery: [null as Node | null, { setQuery: (_, { query }) => query }] }),
    selectors({
        defaultQuery: [
            (s) => [s.currentTeam],
            (currentTeam) => {
                const defaultSourceForTeam = currentTeam && getDefaultEventsQueryForTeam(currentTeam)
                const defaultForScene = getDefaultEventsSceneQuery()
                return defaultSourceForTeam ? { ...defaultForScene, source: defaultSourceForTeam } : defaultForScene
            },
        ],
        query: [(s) => [s.savedQuery, s.defaultQuery], (savedQuery, defaultQuery) => savedQuery || defaultQuery],
    }),
    actionToUrl(({ values }) => ({
        setQuery: () => [
            values.featureFlags[FEATURE_FLAGS.LIVE_EVENTS] ? urls.activity(ActivityTab.ExploreEvents) : urls.events(),
            {},
            objectsEqual(values.query, values.defaultQuery) ? {} : { q: values.query },
            { replace: true },
        ],
    })),

    urlToAction(({ actions, values }) => {
        const eventsQueryHandler: UrlToActionPayload[keyof UrlToActionPayload] = (_, __, { q: queryParam }): void => {
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
        }
        return {
            [urls.events()]: eventsQueryHandler,
            [urls.activity(ActivityTab.ExploreEvents)]: eventsQueryHandler,
        }
    }),
])
