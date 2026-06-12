import { actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { FileSystemEntry } from '@posthog/query-frontend/schema/schema-general'

import api, { ApiConfig } from 'lib/api'
import { permanentlyMount } from 'lib/utils/kea-logic-builders'
import { teamLogic } from 'scenes/teamLogic'

import type { recentItemsModelType } from './recentItemsModelType'

const RECENTS_FETCH_LIMIT = 20

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
                    } catch {
                        // Recents are a non-essential homepage widget — transient failures (offline,
                        // aborted navigation, blocked requests) shouldn't surface as captured exceptions.
                        return []
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
                    } catch {
                        // See loadRecents: this is a best-effort homepage widget, so transient
                        // fetch failures should degrade to an empty result rather than throw.
                        return {}
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
