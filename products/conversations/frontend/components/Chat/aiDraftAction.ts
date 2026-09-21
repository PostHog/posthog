import type { ChatMessage } from '../../types'

export type AiDraftActionKind = 'reply' | 'question'

export function firstClarifyingQuestion(questions: unknown): string | null {
    if (!Array.isArray(questions)) {
        return null
    }
    for (const item of questions) {
        if (typeof item === 'string' && item.trim()) {
            return item.trim()
        }
    }
    return null
}

export function aiDraftAction(
    message: Pick<ChatMessage, 'authorType' | 'isPrivate' | 'persistAs' | 'clarifyingQuestions'>
): AiDraftActionKind | null {
    if (message.authorType !== 'AI' || !message.isPrivate) {
        return null
    }
    if (message.persistAs === 'clarification') {
        return 'question'
    }
    if (message.persistAs === 'findings') {
        return firstClarifyingQuestion(message.clarifyingQuestions) ? 'question' : null
    }
    return 'reply'
}

export function aiDraftComposerText(
    message: Pick<ChatMessage, 'content' | 'authorType' | 'isPrivate' | 'persistAs' | 'clarifyingQuestions'>
): string {
    if (aiDraftAction(message) === 'question') {
        return firstClarifyingQuestion(message.clarifyingQuestions) ?? message.content
    }
    return message.content
}
