import { actions, afterMount, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import type { SignalTeamConfig } from '../types'
import type { signalTeamConfigLogicType } from './signalTeamConfigLogicType'

/**
 * Team-level Self-driving config (singleton per team). Wraps the
 * `signals/team_config` endpoint via `api.signalTeamConfig`. Surfaces the
 * team-wide default PR auto-start threshold (which seeds every user's effective
 * threshold until they set a personal override in `userAutonomyLogic`) and the
 * team-wide default Slack notification channel, where every actionable report is
 * posted regardless of whether a suggested reviewer resolves. The auto-start
 * field is non-nullable (P0–P4), so unlike the per-user override there is no
 * "Never" option; the channel is nullable and `null` disables the team default.
 */
export const signalTeamConfigLogic = kea<signalTeamConfigLogicType>([
    path(['scenes', 'inbox', 'logics', 'signalTeamConfigLogic']),
    actions({
        // Partial update of the singleton, e.g. `{ default_slack_notification_channel: null }`
        // to clear the team channel. One action serves every patchable field.
        patchTeamConfig: (patch: Partial<SignalTeamConfig>) => ({ patch }),
    }),
    loaders({
        teamConfig: [
            null as SignalTeamConfig | null,
            {
                loadTeamConfig: async () => {
                    return await api.signalTeamConfig.get()
                },
            },
        ],
    }),
    reducers({
        // Optimistically reflect the patched values so the controls don't flicker
        // back to the stale ones while the request is in flight.
        teamConfig: {
            patchTeamConfig: (state, { patch }) => (state ? { ...state, ...patch } : state),
        },
    }),
    listeners(({ actions }) => ({
        patchTeamConfig: async ({ patch }) => {
            try {
                const config = await api.signalTeamConfig.update(patch)
                actions.loadTeamConfigSuccess(config)
            } catch (error: any) {
                lemonToast.error(error?.detail ?? error?.message ?? 'Failed to update team self-driving settings')
                // Resync so the optimistic value doesn't linger after a failed update.
                actions.loadTeamConfig()
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadTeamConfig()
    }),
])
