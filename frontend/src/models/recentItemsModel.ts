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
/**
 * Fraction of loader timeouts to forward to error tracking. The file_system recents fetch still
 * stalls past {@link LOADER_TIMEOUT_MS} for a residual cohort of users daily; capturing every hang
 * floods error tracking without adding signal. Sampling keeps enough volume to watch the endpoint's
 * health — divide the observed count by this rate to estimate the true rate — while cutting the
 * noise. The widget degrades to an empty list either way, so a dropped capture loses no user-facing
 * behavior.
 */
const TIMEOUT_CAPTURE_SAMPLE_RATE = 0.1

function captureLoaderTimeout(error: PromiseTimeoutError): void {
    if (Math.random() >= TIMEOUT_CAPTURE_SAMPLE_RATE) {
        return
    }
    posthog.captureException(error, { loader_timeout_sample_rate: TIMEOUT_CAPTURE_SAMPLE_RATE })
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
                        // skeleton; the timeout lets the loader settle. Surface a sampled slice of
                        // these hangs so the stuck state stays visible without flooding error tracking.
                        if (error instanceof PromiseTimeoutError) {
                            captureLoaderTimeout(error)
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
                        // See loadRecents: a sampled slice of hung fetches is surfaced, while
                        // transient failures degrade to an empty result rather than throw.
                        if (error instanceof PromiseTimeoutError) {
                            captureLoaderTimeout(error)
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
