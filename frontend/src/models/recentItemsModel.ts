import { actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import api, { ApiConfig } from 'lib/api'
import { PromiseTimeoutError, withTimeout } from 'lib/utils/async'
import { permanentlyMount } from 'lib/utils/kea-logic-builders'
import { teamLogic } from 'scenes/teamLogic'

import { FileSystemEntry } from '~/queries/schema/schema-general'

import type { recentItemsModelType } from './recentItemsModelType'

const RECENTS_FETCH_LIMIT = 20
/**
 * Upper bound on how long a recents/scene-views fetch may run before we give up. A stalled
 * request that never settles would otherwise leave `recentsHasLoaded` / `sceneLogViewsHasLoaded`
 * false forever, freezing the global search page on a loading skeleton (these flags only flip
 * via the loaders' Success/Failure reducers).
 */
const LOADER_TIMEOUT_MS = 10000

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
                        const response = await withTimeout(
                            (signal) =>
                                api.fileSystem.list({
                                    orderBy: '-last_viewed_at',
                                    notType: 'folder',
                                    limit: RECENTS_FETCH_LIMIT,
                                    signal,
                                }),
                            LOADER_TIMEOUT_MS,
                            'loadRecents timed out'
                        )
                        return response.results
                    } catch (error) {
                        // A stalled fetch that never settles would freeze the search page on a
                        // skeleton; the timeout lets the loader settle. Surface the hang so these
                        // previously-invisible stuck states show up as captured exceptions.
                        if (error instanceof PromiseTimeoutError) {
                            posthog.captureException(error)
                        }
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
                        const results = await withTimeout(
                            (signal) => api.fileSystemLogView.list({ type: 'scene', signal }),
                            LOADER_TIMEOUT_MS,
                            'loadSceneLogViews timed out'
                        )
                        const record: Record<string, string> = {}
                        for (const { ref, viewed_at } of results) {
                            const current = record[ref]
                            if (!current || Date.parse(viewed_at) > Date.parse(current)) {
                                record[ref] = viewed_at
                            }
                        }
                        return record
                    } catch (error) {
                        // See loadRecents: a hung fetch is surfaced, while transient failures
                        // degrade to an empty result rather than throw.
                        if (error instanceof PromiseTimeoutError) {
                            posthog.captureException(error)
                        }
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
