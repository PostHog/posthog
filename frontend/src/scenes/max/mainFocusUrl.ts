import { urls } from 'scenes/urls'

export interface MainFocusUrlInput {
    /** Whether the panel is running the new PostHog AI view rather than the legacy Max chat. */
    isNewView: boolean
    /** The task the new view's panel currently has open, if any. */
    activeTaskId?: string
    /** The conversation the legacy view currently has open, if any. */
    conversationId: string | null
}

/**
 * Where the side panel's "Open as main focus" button goes. The new view runs tasks rather than Max
 * conversations, so its open chat is a task run and `conversationId` is always null there — reading
 * the conversation alone lands the user on an empty `/ai` instead of what they were reading.
 */
export function mainFocusUrl({ isNewView, activeTaskId, conversationId }: MainFocusUrlInput): string {
    if (isNewView) {
        return activeTaskId ? urls.taskDetail(activeTaskId) : urls.ai()
    }
    return urls.ai(conversationId ?? undefined)
}
