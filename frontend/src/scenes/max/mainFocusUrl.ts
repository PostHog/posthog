import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import type { ActiveCreation } from 'products/posthog_ai/frontend/api/logics'

export interface MainFocusUrlInput {
    /** Whether the panel is running the new PostHog AI view rather than the legacy Max chat. */
    isNewView: boolean
    /** The run the new view's panel has open, if any. */
    activeCreation: ActiveCreation | null
    /** The conversation the legacy view has open, if any. */
    conversationId: string | null
}

/**
 * Where the side panel's "Open as main focus" button goes, or null when the open chat has nowhere to go
 * yet. The new view's panel runs tasks rather than Max conversations, so its open chat is a task run and
 * `conversationId` stays null there.
 */
export function mainFocusUrl({ isNewView, activeCreation, conversationId }: MainFocusUrlInput): string | null {
    if (!isNewView) {
        return urls.ai(conversationId ?? undefined)
    }
    if (!activeCreation) {
        return urls.ai()
    }
    if (!activeCreation.taskId) {
        // A task still being created has no page to open, and the panel holds the only copy of its
        // pending thread — so the button has to wait rather than send the user somewhere else.
        return null
    }
    // The panel keeps streaming the run it opened, while the task page otherwise defaults to the newest.
    return combineUrl(urls.taskDetail(activeCreation.taskId), { runId: activeCreation.runId }).url
}
