import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { FEATURE_FLAGS, SESSION_RECORDINGS_PLAYLIST_FREE_COUNT } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ActivityFilters } from '~/layout/navigation-3000/sidepanel/panels/activity/activityForSceneLogic'
import { ActivityScope, Breadcrumb, ReplayTabs } from '~/types'

import type { sessionReplaySceneLogicType } from './sessionReplaySceneLogicType'

export const humanFriendlyTabName = (tab: ReplayTabs): string => {
    switch (tab) {
        case ReplayTabs.Home:
            return 'Recordings'
        case ReplayTabs.Playlists:
            return 'Playlists'
        default:
            return capitalizeFirstLetter(tab)
    }
}

export const PLAYLIST_LIMIT_REACHED_MESSAGE = `You have reached the free limit of ${SESSION_RECORDINGS_PLAYLIST_FREE_COUNT} saved playlists`

export const sessionReplaySceneLogic = kea<sessionReplaySceneLogicType>([
    path(() => ['scenes', 'session-recordings', 'sessionReplaySceneLogic']),
    connect({
        values: [featureFlagLogic, ['featureFlags']],
    }),
    actions({
        setTab: (tab: ReplayTabs = ReplayTabs.Home) => ({ tab }),
    }),
    reducers(() => ({
        tab: [
            ReplayTabs.Home as ReplayTabs,
            {
                setTab: (_, { tab }) => tab,
            },
        ],
    })),

    actionToUrl(({ values }) => {
        return {
            setTab: () => [urls.replay(values.tab), router.values.searchParams],
        }
    }),

    selectors(() => ({
        tabs: [
            (s) => [s.featureFlags],
            (featureFlags) => {
                const hasErrorClustering = !!featureFlags[FEATURE_FLAGS.REPLAY_ERROR_CLUSTERING]
                return Object.values(ReplayTabs).filter((tab) => tab != ReplayTabs.Errors || hasErrorClustering)
            },
        ],
        breadcrumbs: [
            (s) => [s.tab],
            (tab): Breadcrumb[] => {
                const breadcrumbs: Breadcrumb[] = []
                if (tab !== ReplayTabs.Home) {
                    breadcrumbs.push({
                        key: Scene.Replay,
                        name: 'Replay',
                        path: urls.replay(),
                    })
                }
                breadcrumbs.push({
                    key: tab,
                    name: humanFriendlyTabName(tab),
                })

                return breadcrumbs
            },
        ],
        activityFilters: [
            () => [router.selectors.searchParams],
            (searchParams): ActivityFilters | null => {
                return searchParams.sessionRecordingId
                    ? {
                          scope: ActivityScope.REPLAY,
                          item_id: searchParams.sessionRecordingId,
                      }
                    : null
            },
        ],
    })),

    urlToAction(({ actions, values }) => {
        return {
            '/replay/:tab': ({ tab }) => {
                if (tab !== values.tab) {
                    actions.setTab(tab as ReplayTabs)
                }
            },
        }
    }),
])
