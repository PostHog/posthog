import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { Breadcrumb, SessionRecordingPlaylistType, SessionRecordingsTabs } from '~/types'
import { urls } from 'scenes/urls'
import { actionToUrl, router, urlToAction } from 'kea-router'

import type { sessionRecordingsLogicType } from './sessionRecordingsLogicType'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { capitalizeFirstLetter } from 'lib/utils'

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

export const sessionRecordingsLogic = kea<sessionRecordingsLogicType>([
    path(() => ['scenes', 'session-recordings', 'root']),
    connect({
        values: [featureFlagLogic, ['featureFlags']],
    }),
    actions({
        setTab: (tab: SessionRecordingsTabs = SessionRecordingsTabs.Recent) => ({ tab }),
        saveNewPlaylist: (playlist: Partial<SessionRecordingPlaylistType>) => ({ playlist }),
    }),
    reducers(({}) => ({
        tab: [
            SessionRecordingsTabs.Recent as SessionRecordingsTabs,
            {
                setTab: (_, { tab }) => tab,
            },
        ],
    })),
    loaders(({}) => ({
        newPlaylist: [
            null as SessionRecordingPlaylistType | null,
            {
                saveNewPlaylist: async ({ playlist }) => {
                    const response = await api.recordings.createPlaylist(playlist)

                    return response
                },
            },
        ],
    })),
    listeners(({}) => ({
        saveNewPlaylistSuccess: async ({ newPlaylist }) => {
            router.actions.push(urls.sessionRecordingPlaylist(newPlaylist.short_id))
        },
    })),
    actionToUrl(({ values }) => {
        return {
            setTab: () => [urls.sessionRecordings(values.tab), router.values.searchParams],
        }
    }),

    selectors(({}) => ({
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
                if (!values.featureFlags[FEATURE_FLAGS.RECORDING_PLAYLISTS]) {
                    return
                }
                router.actions.replace(urls.sessionRecordings(SessionRecordingsTabs.Recent))
            },
            '/recordings/:tab': ({ tab }) => {
                if (!values.featureFlags[FEATURE_FLAGS.RECORDING_PLAYLISTS]) {
                    return
                }

                if (tab !== values.tab) {
                    actions.setTab(tab as SessionRecordingsTabs)
                }
            },
        }
    }),
])
