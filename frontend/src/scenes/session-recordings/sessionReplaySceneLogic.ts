import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { SESSION_RECORDINGS_PLAYLIST_FREE_COUNT } from 'lib/constants'
import { capitalizeFirstLetter } from 'lib/utils'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import { ActivityScope, Breadcrumb, ReplayTabs } from '~/types'

import type { sessionReplaySceneLogicType } from './sessionReplaySceneLogicType'

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

export const PLAYLIST_LIMIT_REACHED_MESSAGE = `You have reached the free limit of ${SESSION_RECORDINGS_PLAYLIST_FREE_COUNT} saved playlists`

export const sessionReplaySceneLogic = kea<sessionReplaySceneLogicType>([
    path(() => ['scenes', 'session-recordings', 'sessionReplaySceneLogic']),
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
        breadcrumbs: [
            (s) => [s.tab],
            (tab: ReplayTabs): Breadcrumb[] => {
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
            (searchParams: Record<string, any>): SidePanelSceneContext | null => {
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
                // we saw a page get stuck in a redirect loop between recent and home
                // see https://posthog.sentry.io/issues/6176801992/?notification_uuid=093e1a3f-c266-4c17-9610-68816996d304&project=1899813&referrer=assigned_activity-email
                // so, we're extra careful that the value being set is a valid tab
                const candidateTab = tab as ReplayTabs
                const validTab = Object.values(ReplayTabs).includes(candidateTab) ? candidateTab : ReplayTabs.Home
                if (validTab !== values.tab) {
                    actions.setTab(validTab)
                }
            },
        }
    }),
])
