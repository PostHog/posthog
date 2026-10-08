import { markdownToHtml } from 'lib/utils/markdown'
import { isTrustedPostHogUrl } from 'lib/utils/trustedUrl'

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

export function aiDraftComposerHtml(
    message: Pick<ChatMessage, 'content' | 'authorType' | 'isPrivate' | 'persistAs' | 'clarifyingQuestions'>
): string {
    // A draft repeats what the customer wrote, so an image ref in the ticket can reach it. The
    // composer loads images, which would make the agent's browser fetch a host the customer chose.
    // DOMParser gives an inert document, so nothing loads while the images are taken out.
    const parsed = new DOMParser().parseFromString(markdownToHtml(aiDraftComposerText(message)), 'text/html')
    for (const image of Array.from(parsed.querySelectorAll('img'))) {
        const source = image.getAttribute('src')
        if (isTrustedPostHogUrl(source ?? undefined)) {
            continue
        }
        image.replaceWith(parsed.createTextNode(image.getAttribute('alt') || source || ''))
    }
    return parsed.body.innerHTML
}
