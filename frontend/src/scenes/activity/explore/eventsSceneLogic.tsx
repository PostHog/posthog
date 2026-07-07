import equal from 'fast-deep-equal'
import { actions, connect, kea, key, listeners, path, reducers, selectors } from 'kea'
import { urlToAction } from 'kea-router'
import { UrlToActionPayload } from 'kea-router/lib/types'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { trackedActionToUrl } from 'lib/logic/scenes/trackedActionToUrl'
import { tabUiStateLogic } from 'lib/logic/tabUiStateLogic'
import { objectsEqual } from 'lib/utils/objects'
import { applyTestAccountFilter, getDefaultEventsSceneQuery } from 'scenes/activity/explore/defaults'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene } from 'scenes/sceneTypes'
import { filterTestAccountsDefaultsLogic } from 'scenes/settings/environment/filterTestAccountDefaultsLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { getDefaultEventsQueryForTeam } from '~/queries/nodes/DataTable/defaultEventsQuery'
import { DataTableNode, Node } from '~/queries/schema/schema-general'
import { ActivityTab, Breadcrumb } from '~/types'

import type { eventsSceneLogicType } from './eventsSceneLogicType'

export const eventsSceneLogic = kea<eventsSceneLogicType>([
    key(() => 'scene'),
    path((key) => ['scenes', 'events', 'eventsSceneLogic', key]),
    connect(() => ({
        values: [
            teamLogic,
            ['currentTeam'],
            featureFlagLogic,
            ['featureFlags'],
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
            actions.setSavedQueryForTab(undefined, 'events', isDefault ? null : query)
        },
    })),
    selectors({
        defaultQuery: [
            (s) => [s.currentTeam, s.filterTestAccountsDefault],
            (currentTeam, filterTestAccountsDefault): DataTableNode => {
                const defaultSourceForTeam = currentTeam && getDefaultEventsQueryForTeam(currentTeam)
                const defaultForScene = getDefaultEventsSceneQuery()
                const base = defaultSourceForTeam
                    ? { ...defaultForScene, source: defaultSourceForTeam }
                    : defaultForScene
                return {
                    ...applyTestAccountFilter(base, currentTeam, filterTestAccountsDefault),
                    showPropertyFilter: true,
                }
            },
        ],
        query: [(s) => [s.savedQuery, s.defaultQuery], (savedQuery, defaultQuery) => savedQuery || defaultQuery],
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: Scene.ExploreEvents,
                    name: sceneConfigurations[Scene.ExploreEvents].name,
                    iconType: sceneConfigurations[Scene.ExploreEvents].iconType || 'default_icon_type',
                },
            ],
        ],
    }),
    trackedActionToUrl(({ values }) => ({
        setQuery: () => [
            urls.activity(ActivityTab.ExploreEvents),
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
                    // restore from the persisted query if present, else fall back to default
                    const persisted = values.savedQueryFor(undefined, 'events')
                    const target = persisted ?? values.defaultQuery
                    if (!objectsEqual(values.query, target)) {
                        actions.setQuery(target)
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
            [urls.activity(ActivityTab.ExploreEvents)]: eventsQueryHandler,
        }
    }),
])
