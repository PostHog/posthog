import { Code, ConnectError } from '@connectrpc/connect'

import { logger } from '~/common/utils/logger'

import { grpcErrorType, personhogRetriesTotal, personhogTerminalErrorsTotal } from './metrics'

const RETRYABLE_CODES = new Set([
    Code.Unavailable,
    Code.DeadlineExceeded,
    Code.ResourceExhausted,
    Code.Aborted,
    Code.Internal,
    Code.Unknown,
])

/**
 * Connect raises `ResourceExhausted` for two very different situations:
 * genuine server-side backpressure (retrying with backoff can succeed) and a
 * response that exceeds the client's `readMaxBytes` cap. The latter is
 * deterministic — the same oversized frame comes back on every attempt — so
 * retrying only multiplies the logged failures without any chance of success.
 * Connect tags the cap-exceeded case with a message mentioning `readMaxBytes`,
 * which is how we tell the two apart.
 */
function isOversizedResponse(error: ConnectError): boolean {
    return error.code === Code.ResourceExhausted && error.rawMessage.includes('readMaxBytes')
}

function isRetryable(error: unknown): boolean {
    if (!(error instanceof ConnectError)) {
        return false
    }
    if (isOversizedResponse(error)) {
        return false
    }
    return RETRYABLE_CODES.has(error.code)
}

function sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms))
}

/**
 * Retry a function with exponential backoff on transient gRPC errors.
 * Non-transient errors are thrown immediately.
 *
 * Emits `personhog_retries_total` on each retried attempt and
 * `personhog_terminal_errors_total` when retries are exhausted or the
 * error is non-retryable — both tagged with method + client + error_type
 * so they align with `personhog_errors_total` from timedGrpc.
 */
export async function withRetry<T>(
    fn: () => Promise<T>,
    client: string,
    method: string,
    maxRetries: number = 2,
    initialDelayMs: number = 50
): Promise<T> {
    let lastError: unknown
    for (let attempt = 0; attempt <= maxRetries; attempt++) {
        try {
            return await fn()
        } catch (error) {
            lastError = error
            if (!isRetryable(error) || attempt === maxRetries) {
                personhogTerminalErrorsTotal.inc({ method, client, error_type: grpcErrorType(error) })
                logger.error(`[${client}/${method}] gRPC call failed`, {
                    error: String(error),
                })
                throw error
            }
            personhogRetriesTotal.inc({ method, client, error_type: grpcErrorType(error) })
            logger.warn(`[${client}/${method}] Retryable gRPC error, retrying`, {
                attempt: attempt + 1,
                maxRetries,
                error: String(error),
            })
            await sleep(initialDelayMs * Math.pow(2, attempt))
        }
    }
    throw lastError
}
