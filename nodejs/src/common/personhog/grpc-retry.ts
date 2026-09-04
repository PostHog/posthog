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
 * Encode the method and client into the error so a slow personhog window no
 * longer collapses every service into one context-free issue. Error tracking
 * hashes the exception type (from `error.name`) on every event, but hashes the
 * message only when the stack does not resolve. A posthog-node capture always
 * carries a resolved stack, so the type is what splits the fingerprint. Set a
 * distinct `name` per client and method so a real read failure surfaces as its
 * own issue. Keep the same context in the message so a person reading the issue
 * still sees the caller. The `ConnectError` code and rawMessage stay unchanged.
 */
function withCallerContext(error: ConnectError, client: string, method: string): ConnectError {
    const context = `personhog ${client}/${method}`
    error.name = context
    error.message = `${context}: ${error.message}`
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
