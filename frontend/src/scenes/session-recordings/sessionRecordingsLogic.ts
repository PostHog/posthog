import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { Breadcrumb, SessionRecordingsTabs } from '~/types'
import { urls } from 'scenes/urls'
import { actionToUrl, router, urlToAction } from 'kea-router'
import type { sessionRecordingsLogicType } from './sessionRecordingsLogicType'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SESSION_RECORDINGS_PLAYLIST_FREE_COUNT } from 'lib/constants'
import { capitalizeFirstLetter } from 'lib/utils'
import { savedSessionRecordingPlaylistModelLogic } from 'scenes/session-recordings/saved-playlists/savedSessionRecordingPlaylistModelLogic'

export const humanFriendlyTabName = (tab: SessionRecordingsTabs): string => {
    switch (tab) {
        case SessionRecordingsTabs.Recent:
            return 'Recent Recordings'
        case SessionRecordingsTabs.Playlists:
            return 'Saved Playlists'
        default:
            return capitalizeFirstLetter(tab)
    }
}

export const PLAYLIST_LIMIT_REACHED_MESSAGE = `You have reached the free limit of ${SESSION_RECORDINGS_PLAYLIST_FREE_COUNT} saved playlists`

export const sessionRecordingsLogic = kea<sessionRecordingsLogicType>([
    path(() => ['scenes', 'session-recordings', 'root']),
    connect(() => ({
        values: [
            featureFlagLogic,
            ['featureFlags'],
            savedSessionRecordingPlaylistModelLogic,
            ['_savedPlaylistLoading'],
        ],
        actions: [
            savedSessionRecordingPlaylistModelLogic,
            ['createSavedPlaylist', 'duplicateSavedPlaylist', 'updateSavedPlaylist'],
        ],
    })),
    actions({
        setTab: (tab: SessionRecordingsTabs = SessionRecordingsTabs.Recent) => ({ tab }),
        saveNewPlaylist: true,
    }),
    reducers(({}) => ({
        tab: [
            SessionRecordingsTabs.Recent as SessionRecordingsTabs,
            {
                setTab: (_, { tab }) => tab,
            },
        ],
    })),

    listeners(({ actions, values }) => ({
        saveNewPlaylist: async () => {
            const filters = router.values.searchParams?.filters
            await actions.createSavedPlaylist(
                {
                    filters: values.tab === SessionRecordingsTabs.Recent ? filters : undefined,
                },
                true
            )
        },
    })),

    actionToUrl(({ values }) => {
        return {
            setTab: () => [urls.sessionRecordings(values.tab), router.values.searchParams],
        }
    }),

    selectors(({}) => ({
        newPlaylistLoading: [(s) => [s._savedPlaylistLoading], (_savedPlaylistLoading) => !!_savedPlaylistLoading],
        breadcrumbs: [
            (s) => [s.tab],
            (tab): Breadcrumb[] => [
                {
                    name: humanFriendlyTabName(tab),
                },
            ],
        ],
    })),

    urlToAction(({ actions, values }) => {
        return {
            [urls.sessionRecordings()]: () => {
                router.actions.replace(urls.sessionRecordings(SessionRecordingsTabs.Recent))
            },
            '/recordings/:tab': ({ tab }) => {
                if (tab !== values.tab) {
                    actions.setTab(tab as SessionRecordingsTabs)
                }
            },
        }
    }),
])
