import { actions, afterMount, kea, listeners, path, reducers } from 'kea'
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
        // Slack notification preferences (suggested-reviewer pings for new inbox items).
        // integration + channel together enable notifications; either null disables them.
        updateSlackNotifications: (updates: {
            integrationId?: number | null
            channel?: string | null
            minPriority?: SignalReportPriority | null
        }) => ({ updates }),
        // Ephemeral view state: whether the workspace/channel pickers are revealed. Lets a user
        // with multiple workspaces (and nothing saved yet) open the pickers to pick one.
        setSlackPickersExpanded: (expanded: boolean) => ({ expanded }),
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
            updateSlackNotifications: (state, { updates }) => ({
                ...(state ?? { autostart_priority: null }),
                ...('integrationId' in updates
                    ? { slack_notification_integration_id: updates.integrationId ?? null }
                    : {}),
                ...('channel' in updates ? { slack_notification_channel: updates.channel ?? null } : {}),
                ...('minPriority' in updates ? { slack_notification_min_priority: updates.minPriority ?? null } : {}),
            }),
        },
        slackPickersExpanded: [
            false,
            {
                setSlackPickersExpanded: (_, { expanded }) => expanded,
            },
        ],
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
        updateSlackNotifications: async ({ updates }) => {
            // Send only the keys the caller passed so unrelated fields (e.g. autostart_priority) aren't wiped.
            const body: Partial<SignalUserAutonomyConfig> = {}
            if ('integrationId' in updates) {
                body.slack_notification_integration_id = updates.integrationId ?? null
            }
            if ('channel' in updates) {
                body.slack_notification_channel = updates.channel ?? null
            }
            if ('minPriority' in updates) {
                body.slack_notification_min_priority = updates.minPriority ?? null
            }
            try {
                await api.signalUserAutonomy.update(body)
            } catch (error: any) {
                lemonToast.error(error?.detail ?? error?.message ?? 'Failed to update Slack notification setting')
            } finally {
                actions.loadAutonomyConfig()
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadAutonomyConfig()
    }),
])
