import { actions, afterMount, kea, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { permanentlyMount } from 'lib/utils/kea-logic-builders'

import { FileSystemEntry } from '~/queries/schema/schema-general'

import type { recentItemsModelType } from './recentItemsModelType'

const RECENTS_FETCH_LIMIT = 20

export const recentItemsModel = kea<recentItemsModelType>([
    path(['models', 'recentItemsModel']),

    actions({
        recordView: (type: string, ref: string) => ({ type, ref }),
    }),

    loaders({
        recents: [
            [] as FileSystemEntry[],
            {
                loadRecents: async () => {
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
    }),

    afterMount(({ actions }) => {
        actions.loadRecents()
        actions.loadSceneLogViews()
    }),

    permanentlyMount(),
])
