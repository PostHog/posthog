export type RedisErrorReason = 'timeout' | 'connection' | 'reply' | 'other'

const CONNECTION_ERROR_NAMES = new Set(['AbortError', 'MaxRetriesPerRequestError'])

const CONNECTION_ERROR_MESSAGE_MARKERS = [
    'Connection is closed.',
    'ECONNREFUSED',
    'ECONNRESET',
    'EPIPE',
    'ETIMEDOUT',
    'EHOSTUNREACH',
    'ENETUNREACH',
    'ENOTFOUND',
    'EAI_AGAIN',
]

// ioredis rejects a timed-out command with a plain Error, so the message is the only thing that identifies it.
export function redisErrorReason(error: unknown): RedisErrorReason {
    if (!(error instanceof Error)) {
        return 'other'
    }
    if (error.message === 'Command timed out') {
        return 'timeout'
    }
    if (error.name === 'ReplyError') {
        return 'reply'
    }
    if (
        CONNECTION_ERROR_NAMES.has(error.name) ||
        CONNECTION_ERROR_MESSAGE_MARKERS.some((marker) => error.message.includes(marker))
    ) {
        return 'connection'
    }
    return 'other'
}
