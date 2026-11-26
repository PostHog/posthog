import { normalizeMessages } from './messageNormalization'
import { extractContentText } from './sentimentUtils'
import type { CompatMessage } from './types'
import { isOTelPartsMessage } from './utils'

// `index` is a position in the raw $ai_input array, which is the key the backend sentiment classifier stores each result under.
function getRawMessage(aiInput: unknown, index: number): unknown {
    try {
        const parsed = typeof aiInput === 'string' ? JSON.parse(aiInput) : aiInput
        return Array.isArray(parsed) && index >= 0 && index < parsed.length ? parsed[index] : undefined
    } catch {
        return undefined
    }
}

function toCompatMessage(message: unknown): CompatMessage | null {
    try {
        return normalizeMessages([message], 'user').messages[0] ?? null
    } catch {
        return null
    }
}

function parseJSON(text: string): unknown {
    try {
        return JSON.parse(text)
    } catch {
        return null
    }
}

function getContentText(content: unknown): string {
    if (typeof content !== 'string') {
        return extractContentText(content)
    }
    // Detect JSON-encoded structured content (e.g. '{"content":[{"text":"..."}]}')
    const trimmed = content.trim()
    const decoded = trimmed.startsWith('{') || trimmed.startsWith('[') ? extractContentText(parseJSON(trimmed)) : ''
    return decoded || content
}

export function getMessageAtIndex(aiInput: unknown, index: number): CompatMessage | null {
    const message = getRawMessage(aiInput, index)
    return message === undefined ? null : toCompatMessage(message)
}

export function getMessageText(aiInput: unknown, index: number): string {
    const message = getRawMessage(aiInput, index)
    if (isOTelPartsMessage(message)) {
        return getContentText(toCompatMessage(message)?.content)
    }
    return getContentText(
        typeof message === 'object' && message !== null && 'content' in message ? message.content : undefined
    )
}
