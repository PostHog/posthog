import { actions, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import type { SignalReportPriority, SignalUserAutonomyConfig } from '../types'
import type { userAutonomyLogicType } from './userAutonomyLogicType'

/**
 * Per-user Self-driving autonomy override. Wraps the `users/@me/signal_autonomy`
 * endpoint via `api.signalUserAutonomy`. The only field surfaced here is the PR
 * auto-start priority threshold; `null` means "never auto-start" (review first).
 */
export const userAutonomyLogic = kea<userAutonomyLogicType>([
    path(['scenes', 'inbox', 'logics', 'userAutonomyLogic']),
    actions({
        setAutostartPriority: (priority: SignalReportPriority | null) => ({ priority }),
    }),
    loaders({
        autonomyConfig: [
            null as SignalUserAutonomyConfig | null,
            {
                loadAutonomyConfig: async () => {
                    return await api.signalUserAutonomy.get()
                },
            },
        ],
    }),
    reducers({
        // Optimistically reflect the chosen priority so the select doesn't flicker
        // back to the stale value while the request is in flight.
        autonomyConfig: {
            setAutostartPriority: (state, { priority }) => ({
                ...(state ?? { autostart_priority: null }),
                autostart_priority: priority,
            }),
        },
    }),
    listeners(({ actions }) => ({
        setAutostartPriority: async ({ priority }) => {
            try {
                await api.signalUserAutonomy.update({ autostart_priority: priority })
            } catch (error: any) {
                lemonToast.error(error?.detail ?? error?.message ?? 'Failed to update auto-start threshold')
            } finally {
                actions.loadAutonomyConfig()
            }
        },
    })),
])
