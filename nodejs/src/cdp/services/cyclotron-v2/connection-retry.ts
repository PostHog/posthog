import { Counter } from 'prom-client'

import { logger } from '~/common/utils/logger'

const CONNECTION_RETRY_BACKOFF_MS = [100, 500]

const NETWORK_ERROR_CODES = new Set([
    'ECONNRESET',
    'ECONNREFUSED',
    'EPIPE',
    'ETIMEDOUT',
    'EHOSTUNREACH',
    'ENETUNREACH',
    'EAI_AGAIN',
])
const SERVER_SHUTDOWN_SQLSTATES = new Set(['57P01', '57P02', '57P03'])
const CONNECTION_EXCEPTION_SQLSTATE_CLASS = '08'
const DROPPED_CLIENT_MESSAGES = [
    'Connection terminated',
    'Client has encountered a connection error and is not queryable',
]

const writeRetriesCounter = new Counter({
    name: 'cdp_cyclotron_v2_write_retries_total',
    help: 'Job writes retried on a fresh connection after their Postgres connection dropped',
    labelNames: ['write'],
})

function isDroppedConnectionError(error: unknown): boolean {
    if (!(error instanceof Error)) {
        return false
    }
    const code = (error as { code?: unknown }).code
    if (typeof code === 'string') {
        return (
            NETWORK_ERROR_CODES.has(code) ||
            SERVER_SHUTDOWN_SQLSTATES.has(code) ||
            code.startsWith(CONNECTION_EXCEPTION_SQLSTATE_CLASS)
        )
    }
    return DROPPED_CLIENT_MESSAGES.some((message) => error.message.startsWith(message))
}

export async function withConnectionRetry<T>(write: string, run: () => Promise<T>): Promise<T> {
    for (let attempt = 0; ; attempt++) {
        try {
            return await run()
        } catch (error) {
            const backoffMs = CONNECTION_RETRY_BACKOFF_MS[attempt]
            if (backoffMs === undefined || !isDroppedConnectionError(error)) {
                throw error
            }
            writeRetriesCounter.labels({ write }).inc()
            logger.warn('🔁', 'Cyclotron job write retried after its Postgres connection dropped', {
                write,
                attempt: attempt + 1,
                error: String(error),
            })
            await new Promise((resolve) => setTimeout(resolve, backoffMs))
        }
    }
}
