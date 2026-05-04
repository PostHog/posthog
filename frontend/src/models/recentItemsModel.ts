import { actions, afterMount, kea, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { permanentlyMount } from 'lib/utils/kea-logic-builders'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
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
                // Pick up renames/path changes that come back from refreshTreeItem so the
                // recents dropdown reflects the latest title without a page reload.
                [projectTreeDataLogic.actionTypes.addLoadedResults]: (state, { results }) => {
                    const updatesById: Record<string, FileSystemEntry> = {}
                    for (const result of results.results) {
                        if (result.id) {
                            updatesById[result.id] = result
                        }
                    }
                    let changed = false
                    const next = state.map((entry) => {
                        if (!entry.id) {
                            return entry
                        }
                        const update = updatesById[entry.id]
                        if (!update) {
                            return entry
                        }
                        if (update.path === entry.path && update.href === entry.href) {
                            return entry
                        }
                        changed = true
                        return { ...entry, path: update.path, href: update.href, meta: update.meta }
                    })
                    return changed ? next : state
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

    afterMount(({ actions }) => {
        actions.loadRecents()
        actions.loadSceneLogViews()
    }),

    permanentlyMount(),
])
