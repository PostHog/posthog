import equal from 'fast-deep-equal'
import { actions, connect, kea, key, listeners, path, reducers, selectors } from 'kea'
import { urlToAction } from 'kea-router'
import { UrlToActionPayload } from 'kea-router/lib/types'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { trackedActionToUrl } from 'lib/logic/scenes/trackedActionToUrl'
import { tabUiStateLogic } from 'lib/logic/tabUiStateLogic'
import { objectsEqual } from 'lib/utils/objects'
import { applyTestAccountFilter, getDefaultSessionsSceneQuery } from 'scenes/activity/explore/defaults'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene } from 'scenes/sceneTypes'
import { filterTestAccountsDefaultsLogic } from 'scenes/settings/environment/filterTestAccountDefaultsLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { DataTableNode, Node } from '~/queries/schema/schema-general'
import { ActivityTab, Breadcrumb } from '~/types'

import type { sessionsSceneLogicType } from './sessionsSceneLogicType'

export const sessionsSceneLogic = kea<sessionsSceneLogicType>([
    key(() => 'scene'),
    path((key) => ['scenes', 'sessions', 'sessionsSceneLogic', key]),
    connect(() => ({
        values: [
            teamLogic,
            ['currentTeam'],
            filterTestAccountsDefaultsLogic,
            ['filterTestAccountsDefault'],
            tabUiStateLogic,
            ['savedQueryFor'],
        ],
        actions: [tabUiStateLogic, ['setSavedQueryForTab']],
    })),

    actions({ setQuery: (query: Node) => ({ query }) }),
    reducers({ savedQuery: [null as Node | null, { setQuery: (_, { query }) => query }] }),
    listeners(({ actions, values }) => ({
        setQuery: ({ query }) => {
            const isDefault = objectsEqual(query, values.defaultQuery)
            actions.setSavedQueryForTab(undefined, 'sessions', isDefault ? null : query)
        },
    })),
    selectors({
        defaultQuery: [
            (s) => [s.currentTeam, s.filterTestAccountsDefault],
            (currentTeam, filterTestAccountsDefault): DataTableNode =>
                applyTestAccountFilter(getDefaultSessionsSceneQuery(), currentTeam, filterTestAccountsDefault),
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
    trackedActionToUrl(({ values }) => ({
        setQuery: () => [
            urls.activity(ActivityTab.ExploreSessions),
            {},
            objectsEqual(values.query, values.defaultQuery) ? {} : { q: values.query },
            { replace: true },
        ],
    })),

    urlToAction(({ actions, values }) => {
        const sessionsQueryHandler: UrlToActionPayload[keyof UrlToActionPayload] = (_, __, { q: queryParam }): void => {
            // If query hasn't changed, do nothing
            if (equal(queryParam, values.query)) {
                return
            }

            // Handle missing query param - restore from the persisted query, else fall back to default
            if (!queryParam) {
                const persisted = values.savedQueryFor(undefined, 'sessions')
                const target = persisted ?? values.defaultQuery
                if (!objectsEqual(values.query, target)) {
                    actions.setQuery(target)
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
])
