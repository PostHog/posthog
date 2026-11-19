import { parseJSON } from '~/common/utils/json-parse'
import { MAX_OUTPUT_CHOICES_LENGTH } from '~/ingestion/pipelines/ai/tools'

export function readToolState(props: Record<string, unknown>, keys: readonly string[]): unknown {
    for (const key of keys) {
        const value = props[key]
        if (value === undefined) {
            continue
        }
        if (typeof value !== 'string') {
            return typeof value === 'object' && value !== null ? value : String(value)
        }
        if (value.length > MAX_OUTPUT_CHOICES_LENGTH) {
            return value
        }
        try {
            const parsed = parseJSON(value)
            // Conversation normalization accepts containers and strings, but drops scalar primitives.
            return typeof parsed === 'object' && parsed !== null ? parsed : value
        } catch {
            return value
        }
    }
    return undefined
}
