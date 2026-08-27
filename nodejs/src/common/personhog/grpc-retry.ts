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

interface RetryBudget {
    maxRetries: number
    initialDelayMs: number
    maxDelayMs: number
    jitter: boolean
}

// Most transient codes fail fast: a genuine backend error should surface quickly.
const DEFAULT_BUDGET: RetryBudget = { maxRetries: 2, initialDelayMs: 50, maxDelayMs: 1_000, jitter: false }

// A slow personhog window makes the client deadline fire. The narrow budget cannot
// ride out that window, so DeadlineExceeded gets more attempts and jittered backoff.
// Jitter spreads the retries of many concurrent callers, so they do not all hit
// personhog again at the same instant while it recovers.
const DEADLINE_BUDGET: RetryBudget = { maxRetries: 5, initialDelayMs: 100, maxDelayMs: 2_000, jitter: true }

function budgetFor(error: ConnectError): RetryBudget {
    return error.code === Code.DeadlineExceeded ? DEADLINE_BUDGET : DEFAULT_BUDGET
}

function backoffMs(budget: RetryBudget, attempt: number): number {
    const capped = Math.min(budget.maxDelayMs, budget.initialDelayMs * Math.pow(2, attempt))
    return budget.jitter ? Math.random() * capped : capped
}

function isRetryable(error: unknown): error is ConnectError {
    return error instanceof ConnectError && RETRYABLE_CODES.has(error.code)
}

/**
 * Encode the method and client into the error message. Error tracking mints one
 * fingerprint per distinct message, so a raw `[deadline_exceeded] the operation
 * timed out` collapses every service and method into one context-free issue.
 * A distinct message per method and client splits them, so a real read failure
 * stays visible.
 */
function withCallerContext(error: ConnectError, client: string, method: string): ConnectError {
    error.message = `personhog ${client}/${method}: ${error.message}`
    return error
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
 * Retry a function with exponential backoff on transient gRPC errors.
 * The retry budget depends on the error code: DeadlineExceeded rides out a
 * slow personhog window with a wider, jittered budget, while other transient
 * codes fail fast. Non-transient errors are thrown immediately.
 *
 * Emits `personhog_retries_total` on each retried attempt and
 * `personhog_terminal_errors_total` when retries are exhausted or the
 * error is non-retryable — both tagged with method + client + error_type
 * so they align with `personhog_errors_total` from timedGrpc.
 */
export async function withRetry<T>(fn: () => Promise<T>, client: string, method: string): Promise<T> {
    for (let attempt = 0; ; attempt++) {
        try {
            return await fn()
        } catch (error) {
            if (!isRetryable(error)) {
                personhogTerminalErrorsTotal.inc({ method, client, error_type: grpcErrorType(error) })
                logger.error(`[${client}/${method}] gRPC call failed`, {
                    error: String(error),
                })
                throw error
            }
            const budget = budgetFor(error)
            if (attempt >= budget.maxRetries) {
                personhogTerminalErrorsTotal.inc({ method, client, error_type: grpcErrorType(error) })
                logger.error(`[${client}/${method}] gRPC call failed`, {
                    error: String(error),
                })
                throw tagRetriable(withCallerContext(error, client, method))
            }
            personhogRetriesTotal.inc({ method, client, error_type: grpcErrorType(error) })
            logger.warn(`[${client}/${method}] Retryable gRPC error, retrying`, {
                attempt: attempt + 1,
                maxRetries: budget.maxRetries,
                error: String(error),
            })
            await sleep(backoffMs(budget, attempt))
        }
    }
}
