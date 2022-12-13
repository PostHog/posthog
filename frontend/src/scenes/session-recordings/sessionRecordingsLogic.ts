import { actions, kea, path, reducers, selectors } from 'kea'
import { Breadcrumb, SessionRecordingsTabs } from '~/types'
import { urls } from 'scenes/urls'
import { actionToUrl, router, urlToAction } from 'kea-router'
import type { sessionRecordingsLogicType } from './sessionRecordingsLogicType'
import { SESSION_RECORDINGS_PLAYLIST_FREE_COUNT } from 'lib/constants'
import { capitalizeFirstLetter } from 'lib/utils'

export const humanFriendlyTabName = (tab: SessionRecordingsTabs): string => {
    switch (tab) {
        case SessionRecordingsTabs.Recent:
            return 'Recent Recordings'
        case SessionRecordingsTabs.Playlists:
            return 'Playlists'
        case SessionRecordingsTabs.FilePlayback:
            return 'Playback from file'
        default:
            return capitalizeFirstLetter(tab)
    }
}

export const PLAYLIST_LIMIT_REACHED_MESSAGE = `You have reached the free limit of ${SESSION_RECORDINGS_PLAYLIST_FREE_COUNT} saved playlists`

export const sessionRecordingsLogic = kea<sessionRecordingsLogicType>([
    path(() => ['scenes', 'session-recordings', 'root']),
    actions({
        setTab: (tab: SessionRecordingsTabs = SessionRecordingsTabs.Recent) => ({ tab }),
    }),
    reducers(({}) => ({
        tab: [
            SessionRecordingsTabs.Recent as SessionRecordingsTabs,
            {
                setTab: (_, { tab }) => tab,
            },
        ],
    })),

    actionToUrl(({ values }) => {
        return {
            setTab: () => [urls.sessionRecordings(values.tab), router.values.searchParams],
        }
    }),

    selectors(({}) => ({
        breadcrumbs: [
            (s) => [s.tab],
            (tab): Breadcrumb[] => {
                const breadcrumbs: Breadcrumb[] = []
                if (tab !== SessionRecordingsTabs.Recent) {
                    breadcrumbs.push({
                        name: 'Recordings',
                        path: urls.sessionRecordings(),
                    })
                }
                breadcrumbs.push({
                    name: humanFriendlyTabName(tab),
                })

                return breadcrumbs
            },
        ],
    })),

    urlToAction(({ actions, values }) => {
        return {
            '/recordings/:tab': ({ tab }) => {
                if (tab !== values.tab) {
                    actions.setTab(tab as SessionRecordingsTabs)
                }
            },
        }
    }),
])
