import { actions, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import type { SignalReportPriority, SignalTeamConfig } from '../types'
import type { signalTeamConfigLogicType } from './signalTeamConfigLogicType'

/**
 * Team-level Self-driving config (singleton per team). Wraps the
 * `signals/team_config` endpoint via `api.signalTeamConfig`. The field surfaced
 * here is the team-wide default PR auto-start threshold, which seeds every
 * user's effective threshold until they set a personal override
 * (`userAutonomyLogic`). The backend field is non-nullable (P0–P4), so unlike
 * the per-user override there is no "Never" option here.
 */
export const signalTeamConfigLogic = kea<signalTeamConfigLogicType>([
    path(['scenes', 'inbox', 'logics', 'signalTeamConfigLogic']),
    actions({
        setDefaultAutostartPriority: (priority: SignalReportPriority) => ({ priority }),
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
        // Optimistically reflect the chosen priority so the select doesn't flicker
        // back to the stale value while the request is in flight.
        teamConfig: {
            setDefaultAutostartPriority: (state, { priority }) => ({
                ...(state ?? { default_autostart_priority: null }),
                default_autostart_priority: priority,
            }),
        },
    }),
    listeners(({ actions }) => ({
        setDefaultAutostartPriority: async ({ priority }) => {
            try {
                await api.signalTeamConfig.update({ default_autostart_priority: priority })
            } catch (error: any) {
                lemonToast.error(
                    error?.detail ?? error?.message ?? 'Failed to update team default auto-start threshold'
                )
            } finally {
                actions.loadTeamConfig()
            }
        },
    })),
])
