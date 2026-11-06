import type { Conversation } from '~/types'

export const RESEARCH_BETA_NOTICE = 'Research mode is a free beta feature with lower daily limits'
export const QUEUED_MESSAGES_HEADING = 'Up next'
export const SUPPORT_SESSION_NOTICE = "Support agent session — this conversation won't be visible to the customer"
export const SUPPORT_OVERRIDE_LABEL = "I understand this will add to the customer's conversation"

export type ComposerPlaceholder =
    | { kind: 'shared'; text: string }
    | { kind: 'thinking'; text: string }
    | { kind: 'custom'; text: string }
    | { kind: 'prompt'; lead: string; hint: string }

export function composerPlaceholder({
    conversation,
    isSharedThread,
    threadLoading,
    isThreadVisible,
    placeholder,
}: {
    conversation: Conversation | null
    isSharedThread: boolean
    threadLoading: boolean
    isThreadVisible?: boolean
    placeholder?: string
}): ComposerPlaceholder {
    if (conversation && isSharedThread) {
        return {
            kind: 'shared',
            text: `This thread was shared with you by ${conversation.user.first_name} ${conversation.user.last_name}`,
        }
    }
    if (threadLoading) {
        return { kind: 'thinking', text: 'Thinking…' }
    }
    if (isThreadVisible && placeholder) {
        return { kind: 'custom', text: placeholder }
    }
    return { kind: 'prompt', lead: isThreadVisible ? 'Ask follow-up' : 'Ask a question', hint: 'or / for commands' }
}
