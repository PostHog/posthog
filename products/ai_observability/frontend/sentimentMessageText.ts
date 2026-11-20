import { normalizeMessages } from './messageNormalization'
import { extractContentText } from './sentimentUtils'
import type { CompatMessage } from './types'

/**
 * Retrieves the message at the given index from the raw $ai_input array.
 * The index corresponds to the position in the original messages array
 * (as used by the backend sentiment classifier).
 */
export function getMessageAtIndex(aiInput: unknown, index: number): CompatMessage | null {
    try {
        const parsed = typeof aiInput === 'string' ? JSON.parse(aiInput) : aiInput
        if (!Array.isArray(parsed) || index < 0 || index >= parsed.length) {
            return null
        }
        const normalized = normalizeMessages([parsed[index]], 'user').messages
        return normalized[0] ?? null
    } catch {
        return null
    }
}

export function getTextContent(message: CompatMessage): string {
    if (typeof message.content === 'string') {
        // Detect JSON-encoded structured content (e.g. '{"content":[{"text":"..."}]}')
        const trimmed = message.content.trim()
        if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
            try {
                const parsed = JSON.parse(trimmed)
                const extracted = extractContentText(parsed)
                if (extracted) {
                    return extracted
                }
            } catch {
                // Not valid JSON, return as-is
            }
        }
        return message.content
    }
    return extractContentText(message.content)
}
