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
    // No caller passes an abort signal, so Canceled is always a stream the peer reset, as a pod leaving does.
    Code.Canceled,
])

// A server sheds with RESOURCE_EXHAUSTED when it is at capacity: identity's
// load shed and the leader's full dirty index both do. A fast retry only adds
// load to a saturated service, so these retries wait longer.
const CAPACITY_INITIAL_DELAY_MS = 250

function isRetryable(error: unknown): error is ConnectError {
    return error instanceof ConnectError && RETRYABLE_CODES.has(error.code)
}

/**
 * Tag a terminal transient error as retriable so outer retry layers (pipeline
 * chunk retry, LazyLoader loaderRetry) can keep retrying after the client-level
 * budget here is exhausted. Non-transient errors are left untagged so
 * unexpected failures surface loudly instead of being absorbed.
 */
function tagRetriable(error: ConnectError): ConnectError & { isRetriable: true } {
    return Object.assign(error, { isRetriable: true as const })
}

function sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms))
}

/**
 * Retries beyond the first attempt. Exported so a caller that must wait out
 * another caller's full transport budget can derive its bound from this.
 */
export const TRANSPORT_MAX_RETRIES = 2

export const TRANSPORT_MAX_BACKOFF_MS = Array.from(
    { length: TRANSPORT_MAX_RETRIES },
    (_, attempt) => 2 * CAPACITY_INITIAL_DELAY_MS * Math.pow(2, attempt)
).reduce((total, delay) => total + delay, 0)

function backoffMs(error: ConnectError, attempt: number, initialDelayMs: number): number {
    const base = error.code === Code.ResourceExhausted ? CAPACITY_INITIAL_DELAY_MS : initialDelayMs
    const delay = base * Math.pow(2, attempt)
    return delay + Math.random() * delay
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
    maxRetries: number = TRANSPORT_MAX_RETRIES,
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
                throw isRetryable(error) ? tagRetriable(error) : error
            }
            personhogRetriesTotal.inc({ method, client, error_type: grpcErrorType(error) })
            logger.warn(`[${client}/${method}] Retryable gRPC error, retrying`, {
                attempt: attempt + 1,
                maxRetries,
                error: String(error),
            })
            await sleep(backoffMs(error, attempt, initialDelayMs))
        }
    }
    throw lastError
}
