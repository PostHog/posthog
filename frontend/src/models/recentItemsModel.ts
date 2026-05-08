import { actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api, { ApiConfig } from 'lib/api'
import { permanentlyMount } from 'lib/utils/kea-logic-builders'
import { teamLogic } from 'scenes/teamLogic'

import { FileSystemEntry } from '~/queries/schema/schema-general'

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

                    const response = await api.fileSystem.list({
                        orderBy: '-last_viewed_at',
                        notType: 'folder',
                        limit: RECENTS_FETCH_LIMIT,
                    })
                    return response.results
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

                    const results = await api.fileSystemLogView.list({ type: 'scene' })
                    const record: Record<string, string> = {}
                    for (const { ref, viewed_at } of results) {
                        const current = record[ref]
                        if (!current || Date.parse(viewed_at) > Date.parse(current)) {
                            record[ref] = viewed_at
                        }
                    }
                    return record
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
