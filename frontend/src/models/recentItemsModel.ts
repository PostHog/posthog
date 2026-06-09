import { actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api, { ApiConfig, ApiError } from 'lib/api'
import { permanentlyMount } from 'lib/utils/kea-logic-builders'
import { teamLogic } from 'scenes/teamLogic'

import { FileSystemEntry } from '~/queries/schema/schema-general'

import type { recentItemsModelType } from './recentItemsModelType'

const RECENTS_FETCH_LIMIT = 20

// This loader is permanently mounted and fires on every team load, so transient browser-level
// fetch failures (offline, CORS, navigation aborts) would otherwise flood error tracking. Those
// never reach the server, so `handleFetch` wraps them in an `ApiError` without an HTTP status,
// while aborted requests surface as an `AbortError`. Real HTTP errors keep their numeric status
// and must keep propagating so genuinely broken requests stay visible.
function isTransientFetchError(error: unknown): boolean {
    if ((error as { name?: string })?.name === 'AbortError') {
        return true
    }
    return error instanceof ApiError && error.status === undefined
}

export const recentItemsModel = kea<recentItemsModelType>([
    path(['models', 'recentItemsModel']),

    connect(() => ({
        actions: [teamLogic, ['loadCurrentTeamSuccess']],
    })),

    actions({
        recordView: (type: string, ref: string) => ({ type, ref }),
    }),

    loaders({
        recents: [
            [] as FileSystemEntry[],
            {
                loadRecents: async () => {
                    if (!ApiConfig.hasCurrentTeamId()) {
                        return []
                    }

                    try {
                        const response = await api.fileSystem.list({
                            orderBy: '-last_viewed_at',
                            notType: 'folder',
                            limit: RECENTS_FETCH_LIMIT,
                        })
                        return response.results
                    } catch (error) {
                        if (isTransientFetchError(error)) {
                            return []
                        }
                        throw error
                    }
                },
            },
        ],
        sceneLogViewsByRef: [
            {} as Record<string, string>,
            {
                loadSceneLogViews: async () => {
                    if (!ApiConfig.hasCurrentTeamId()) {
                        return {}
                    }

                    try {
                        const results = await api.fileSystemLogView.list({ type: 'scene' })
                        const record: Record<string, string> = {}
                        for (const { ref, viewed_at } of results) {
                            const current = record[ref]
                            if (!current || Date.parse(viewed_at) > Date.parse(current)) {
                                record[ref] = viewed_at
                            }
                        }
                        return record
                    } catch (error) {
                        if (isTransientFetchError(error)) {
                            return {}
                        }
                        throw error
                    }
                },
            },
        ],
    }),

    reducers({
        recents: [
            [] as FileSystemEntry[],
            {
                recordView: (state, { type, ref }) => {
                    const idx = state.findIndex((e) => e.type === type && e.ref === ref)
                    if (idx < 0) {
                        return state
                    }
                    const item = { ...state[idx], last_viewed_at: new Date().toISOString() }
                    return [item, ...state.slice(0, idx), ...state.slice(idx + 1)]
                },
            },
        ],
        sceneLogViewsByRef: [
            {} as Record<string, string>,
            {
                recordView: (state, { type, ref }) => {
                    if (type !== 'scene') {
                        return state
                    }
                    return { ...state, [ref]: new Date().toISOString() }
                },
            },
        ],
        recentsHasLoaded: [
            false,
            {
                loadRecentsSuccess: () => true,
                loadRecentsFailure: () => true,
            },
        ],
        sceneLogViewsHasLoaded: [
            false,
            {
                loadSceneLogViewsSuccess: () => true,
                loadSceneLogViewsFailure: () => true,
            },
        ],
    }),

    listeners(({ actions }) => ({
        loadCurrentTeamSuccess: ({ currentTeam }) => {
            if (!currentTeam) {
                return
            }

            actions.loadRecents()
            actions.loadSceneLogViews()
        },
    })),

    afterMount(({ actions }) => {
        if (!ApiConfig.hasCurrentTeamId()) {
            return
        }

        actions.loadRecents()
        actions.loadSceneLogViews()
    }),

    permanentlyMount(),
])
