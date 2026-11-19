import { createHash } from 'crypto'

const sortKeys = (value: unknown): unknown => {
    if (Array.isArray(value)) {
        return value.map(sortKeys)
    }
    if (value !== null && typeof value === 'object') {
        return Object.fromEntries(
            Object.keys(value)
                .sort()
                .map((key) => [key, sortKeys((value as Record<string, unknown>)[key])])
        )
    }
    return value
}

// Callers may rebuild the same request with its object keys in another order on a retry.
export const requestFingerprint = (request: unknown): string =>
    createHash('sha256')
        .update(JSON.stringify(sortKeys(request)))
        .digest('hex')

export type ReplayFields = Record<string, number>

export type SenderKind = 'email_sandbox'

export type QueuedReply = { replayFields?: ReplayFields; scheduledAt?: string; senderKind?: SenderKind }
