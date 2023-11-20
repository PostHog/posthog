import { actions, kea, path, reducers, selectors } from 'kea'
import { Breadcrumb, ReplayTabs } from '~/types'
import { urls } from 'scenes/urls'
import { actionToUrl, router, urlToAction } from 'kea-router'
import type { sessionRecordingsLogicType } from './sessionRecordingsLogicType'
import { SESSION_RECORDINGS_PLAYLIST_FREE_COUNT } from 'lib/constants'
import { capitalizeFirstLetter } from 'lib/utils'
import { Scene } from 'scenes/sceneTypes'

export const humanFriendlyTabName = (tab: ReplayTabs): string => {
    switch (tab) {
        case ReplayTabs.Recent:
            return 'Recent recordings'
        case ReplayTabs.Playlists:
            return 'Playlists'
        case ReplayTabs.FilePlayback:
            return 'Playback from file'
        default:
            return capitalizeFirstLetter(tab)
    }
}

export const PLAYLIST_LIMIT_REACHED_MESSAGE = `You have reached the free limit of ${SESSION_RECORDINGS_PLAYLIST_FREE_COUNT} saved playlists`

export const sessionRecordingsLogic = kea<sessionRecordingsLogicType>([
    path(() => ['scenes', 'session-recordings', 'root']),
    actions({
        setTab: (tab: ReplayTabs = ReplayTabs.Recent) => ({ tab }),
    }),
    reducers(() => ({
        tab: [
            ReplayTabs.Recent as ReplayTabs,
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
        breadcrumbs: [
            (s) => [s.tab],
            (tab): Breadcrumb[] => {
                const breadcrumbs: Breadcrumb[] = []
                if (tab !== ReplayTabs.Recent) {
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
