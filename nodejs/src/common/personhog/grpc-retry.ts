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

function isRetryable(error: unknown): boolean {
    return error instanceof ConnectError && RETRYABLE_CODES.has(error.code)
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
