import { actions, afterMount, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import type { SignalReportPriority, SignalTeamConfig } from '../types'
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
        setDefaultAutostartPriority: (priority: SignalReportPriority) => ({ priority }),
        // `channel` is the "<id>|#name" target the backend stores; `null` clears the team default.
        setDefaultSlackNotificationChannel: (channel: string | null) => ({ channel }),
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
        // Optimistically reflect the chosen value so the control doesn't flicker
        // back to the stale one while the request is in flight.
        teamConfig: {
            setDefaultAutostartPriority: (state, { priority }) => ({
                ...(state ?? { default_autostart_priority: null }),
                default_autostart_priority: priority,
            }),
            setDefaultSlackNotificationChannel: (state, { channel }) => ({
                ...(state ?? { default_autostart_priority: null }),
                default_slack_notification_channel: channel,
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
        setDefaultSlackNotificationChannel: async ({ channel }) => {
            try {
                await api.signalTeamConfig.update({ default_slack_notification_channel: channel })
            } catch (error: any) {
                lemonToast.error(error?.detail ?? error?.message ?? 'Failed to update team Slack channel')
            } finally {
                actions.loadTeamConfig()
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadTeamConfig()
    }),
])
