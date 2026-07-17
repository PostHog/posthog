import { Pool } from 'pg'

import { LlmGatewayClient, LlmGatewayError } from './llm-gateway.client'
import { LlmStepError, LlmStepRequest } from './llm-step.types'
import { WakeOutcome, wakeParkedLlmJob } from './llm-wake'

const DEFAULT_MAX_ATTEMPTS = 3

const realSleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))

// Orchestrates one LLM request end to end, independent of Kafka/consumer plumbing so it can be
// tested directly: call the gateway (with bounded retry on retriable failures), then wake the
// parked job by id with the completion or, if we gave up, a terminal error. The wake is idempotent
// against redelivery via the (jobId, actionId, nonce) key and the `status = 'available'` guard.
export async function executeLlmRequest(args: {
    request: LlmStepRequest
    gatewayClient: LlmGatewayClient
    pool: Pick<Pool, 'connect'>
    maxAttempts?: number
    sleep?: (ms: number) => Promise<void>
}): Promise<{ outcome: WakeOutcome; error?: LlmStepError }> {
    const { request, gatewayClient, pool } = args
    const maxAttempts = args.maxAttempts ?? DEFAULT_MAX_ATTEMPTS
    const sleep = args.sleep ?? realSleep
    const idempotencyKey = `${request.jobId}:${request.actionId}:${request.nonce}`

    let lastError: LlmStepError | undefined
    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
        try {
            const completion = await gatewayClient.complete(request, { idempotencyKey })
            const outcome = await wakeParkedLlmJob(pool, {
                jobId: request.jobId,
                actionId: request.actionId,
                nonce: request.nonce,
                completion,
            })
            return { outcome }
        } catch (err) {
            const retriable = err instanceof LlmGatewayError ? err.retriable : true
            lastError = { message: err instanceof Error ? err.message : String(err), retriable }
            if (!retriable || attempt === maxAttempts) {
                break
            }
            // Exponential backoff between retries (100ms, 200ms, ...). The parked job's timeout
            // backstop bounds the total; this fleet is I/O-bound so a waiting retry is cheap.
            await sleep(100 * 2 ** (attempt - 1))
        }
    }

    // Terminal failure: wake the job with the error so it takes its on_error path now rather than
    // waiting out the full backstop.
    const outcome = await wakeParkedLlmJob(pool, {
        jobId: request.jobId,
        actionId: request.actionId,
        nonce: request.nonce,
        error: lastError,
    })
    return { outcome, error: lastError }
}
