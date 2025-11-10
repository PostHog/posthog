import equal from 'fast-deep-equal'
import { actions, afterMount, connect, kea, path, reducers, selectors } from 'kea'
import { router } from 'kea-router'
import { UrlToActionPayload } from 'kea-router/lib/types'

import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { tabAwareActionToUrl } from 'lib/logic/scenes/tabAwareActionToUrl'
import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import { objectsEqual } from 'lib/utils'
import { getDefaultSessionsSceneQuery } from 'scenes/activity/explore/defaults'
import { Scene } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Node } from '~/queries/schema/schema-general'
import { ActivityTab, Breadcrumb } from '~/types'

import type { sessionsSceneLogicType } from './sessionsSceneLogicType'

export const sessionsSceneLogic = kea<sessionsSceneLogicType>([
    path(['scenes', 'sessions', 'sessionsSceneLogic']),
    tabAwareScene(),
    connect(() => ({ values: [teamLogic, ['currentTeam'], featureFlagLogic, ['featureFlags']] })),

    actions({ setQuery: (query: Node) => ({ query }) }),
    reducers({ savedQuery: [null as Node | null, { setQuery: (_, { query }) => query }] }),
    selectors({
        defaultQuery: [
            () => [],
            (): Node => {
                return getDefaultSessionsSceneQuery()
            },
        ],
        query: [(s) => [s.savedQuery, s.defaultQuery], (savedQuery, defaultQuery): Node => savedQuery || defaultQuery],
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: Scene.ExploreSessions,
                    name: sceneConfigurations[Scene.ExploreSessions].name,
                    iconType: sceneConfigurations[Scene.ExploreSessions].iconType || 'default_icon_type',
                },
            ],
        ],
    }),
    tabAwareActionToUrl(({ values }) => ({
        setQuery: () => [
            urls.activity(ActivityTab.ExploreSessions),
            {},
            objectsEqual(values.query, values.defaultQuery) ? {} : { q: values.query },
            { replace: true },
        ],
    })),

    tabAwareUrlToAction(({ actions, values }) => {
        const sessionsQueryHandler: UrlToActionPayload[keyof UrlToActionPayload] = (_, __, { q: queryParam }): void => {
            // If query hasn't changed, do nothing
            if (equal(queryParam, values.query)) {
                return
            }

            // Handle missing query param - set default if needed
            if (!queryParam) {
                if (!objectsEqual(values.query, values.defaultQuery)) {
                    actions.setQuery(values.defaultQuery)
                }
                return
            }

            // Handle invalid query param type
            if (typeof queryParam !== 'object') {
                lemonToast.error('Invalid query in URL')
                console.error({ queryParam })
                return
            }

            // Valid query object - update state
            actions.setQuery(queryParam)
        }

        return {
            [urls.activity(ActivityTab.ExploreSessions)]: sessionsQueryHandler,
        }
    }),

    afterMount(({ values }) => {
        if (!values.featureFlags[FEATURE_FLAGS.SESSIONS_EXPLORER]) {
            router.actions.push(urls.activity(ActivityTab.ExploreEvents))
        }
    }),
])
