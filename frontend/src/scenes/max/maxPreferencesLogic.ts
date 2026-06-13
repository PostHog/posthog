import { actions, kea, listeners, path, reducers } from 'kea'
import posthog from 'posthog-js'

import type { maxPreferencesLogicType } from './maxPreferencesLogicType'

// Per-device preference, stored locally so it survives across projects on the same browser.
const AI_SEND_WITH_CMD_ENTER_STORAGE_KEY = 'posthog_ai_send_with_cmd_enter'

/**
 * Lightweight, persisted per-device preferences for the PostHog AI chat input.
 *
 * Kept separate from `maxGlobalLogic` so reading a preference (e.g. from the settings
 * page) doesn't mount the heavier global logic and its conversation-history fetch.
 */
export const maxPreferencesLogic = kea<maxPreferencesLogicType>([
    path(['scenes', 'max', 'maxPreferencesLogic']),
    actions({
        setSendWithCmdEnter: (sendWithCmdEnter: boolean) => ({ sendWithCmdEnter }),
    }),
    reducers({
        // When true, Cmd/Ctrl+Enter sends the message and plain Enter inserts a newline.
        sendWithCmdEnter: [
            false,
            { persist: true, storageKey: AI_SEND_WITH_CMD_ENTER_STORAGE_KEY },
            {
                setSendWithCmdEnter: (_, { sendWithCmdEnter }) => sendWithCmdEnter,
            },
        ],
    }),
    listeners(() => ({
        setSendWithCmdEnter: ({ sendWithCmdEnter }) => {
            posthog.capture('max send with cmd enter preference changed', { sendWithCmdEnter })
        },
    })),
])
