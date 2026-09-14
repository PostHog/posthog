export type RedisErrorReason = 'timeout' | 'connection' | 'reply' | 'other'

const CONNECTION_ERROR_CODES = [
    'ECONNREFUSED',
    'ECONNRESET',
    'EPIPE',
    'ETIMEDOUT',
    'EHOSTUNREACH',
    'ENETUNREACH',
    'ENOTFOUND',
    'EAI_AGAIN',
]

const CONNECTION_CLOSED_MESSAGE = 'Connection is closed.'

// A pooled client queues commands while it reconnects, so a lost server rejects with the same plain "Command timed out" Error as a stalled event loop; the client status at catch time separates the two, because a stall leaves the socket ready.
export function redisErrorReason(error: unknown, clientStatus?: string): RedisErrorReason {
    if (!(error instanceof Error)) {
        return 'other'
    }
    if (error.message === 'Command timed out') {
        return clientStatus === undefined || clientStatus === 'ready' ? 'timeout' : 'connection'
    }
    if (error.name === 'ReplyError') {
        return 'reply'
    }
    const code = (error as NodeJS.ErrnoException).code
    if (
        (code !== undefined && CONNECTION_ERROR_CODES.includes(code)) ||
        error.name === 'AbortError' ||
        error.message === CONNECTION_CLOSED_MESSAGE ||
        CONNECTION_ERROR_CODES.some((marker) => error.message.includes(marker))
    ) {
        return 'connection'
    }
    return 'other'
}
