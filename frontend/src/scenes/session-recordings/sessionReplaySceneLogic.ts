import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { FEATURE_FLAGS, SESSION_RECORDINGS_PLAYLIST_FREE_COUNT } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import { ActivityScope, Breadcrumb, ReplayTabs } from '~/types'
import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'
import type { sessionReplaySceneLogicType } from './sessionReplaySceneLogicType'
import { productLayoutLogic, ProductLayoutConfig } from '~/layout/navigation/TopBar/productLayoutLogic'

export const humanFriendlyTabName = (tab: ReplayTabs): string => {
    switch (tab) {
        case ReplayTabs.Home:
            return 'Recordings'
        case ReplayTabs.Playlists:
            return 'Playlists'
        case ReplayTabs.Templates:
            return 'What to watch'
        default:
            return capitalizeFirstLetter(tab)
    }
}

const tabConfigs: ProductLayoutConfig = {
    baseUrl: '/replay',
    baseTabs: [
        {
            key: ReplayTabs.Home,
            label: humanFriendlyTabName(ReplayTabs.Home),
            url: urls.replay(ReplayTabs.Home),
            default: true,
        },
        {
            key: ReplayTabs.Playlists,
            label: humanFriendlyTabName(ReplayTabs.Playlists),
            url: urls.replay(ReplayTabs.Playlists),
            isNew: true,
        },
        {
            key: ReplayTabs.Templates,
            label: humanFriendlyTabName(ReplayTabs.Templates),
            url: urls.replay(ReplayTabs.Templates),
            isNew: true,
        },
    ]
}

export const PLAYLIST_LIMIT_REACHED_MESSAGE = `You have reached the free limit of ${SESSION_RECORDINGS_PLAYLIST_FREE_COUNT} saved playlists`

export const sessionReplaySceneLogic = kea<sessionReplaySceneLogicType>([
    path(() => ['scenes', 'session-recordings', 'sessionReplaySceneLogic']),
    connect({
        values: [featureFlagLogic, ['featureFlags']],
        actions: [
            productLayoutLogic, ['setProductLayoutConfig']
        ],
    }),
    actions({
        setTab: (tab: ReplayTabs = ReplayTabs.Home) => ({ tab }),
        hideNewBadge: true,
    }),
    reducers(() => ({
        tab: [
            ReplayTabs.Home as ReplayTabs,
            {
                setTab: (_, { tab }) => tab,
            },
        ],
        shouldShowNewBadge: [
            true as boolean,
            { persist: true },
            {
                hideNewBadge: () => false,
            },
        ],
    })),

    listeners(({ actions }) => ({
        setTab: ({ tab }) => {
            if (tab === ReplayTabs.Templates) {
                actions.hideNewBadge()
            }
        },
    })),


    actionToUrl(({ values }) => {
        return {
            setTab: () => [urls.replay(values.tab), router.values.searchParams],
        }
    }),


    selectors(() => ({
        productLayoutTabs: [
            (s) => [s.featureFlags],
            (featureFlags) => {
                const hasTemplates = !!featureFlags[FEATURE_FLAGS.REPLAY_TEMPLATES]
                const tabs = tabConfigs.baseTabs.filter((tab) => (tab.key == ReplayTabs.Templates ? hasTemplates : true))
                return tabs
            },
        ],

        // NEW
        productBaseUrl: [
            (s) => [s.tab],
            () => {
                return tabConfigs.baseUrl
            },
        ],

        tabs: [
            (s) => [s.featureFlags],
            (featureFlags) => {
                const hasTemplates = !!featureFlags[FEATURE_FLAGS.REPLAY_TEMPLATES]
                return Object.values(ReplayTabs).filter((tab) => (tab == ReplayTabs.Templates ? hasTemplates : true))
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
        [SIDE_PANEL_CONTEXT_KEY]: [
            () => [router.selectors.searchParams],
            (searchParams): SidePanelSceneContext | null => {
                return searchParams.sessionRecordingId
                    ? {
                          activity_scope: ActivityScope.REPLAY,
                          activity_item_id: searchParams.sessionRecordingId,
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

    afterMount(({ actions }) => {
        actions.setProductLayoutConfig(tabConfigs)
    }),
])
