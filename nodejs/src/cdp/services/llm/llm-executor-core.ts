import { Pool } from 'pg'

import { LlmBlobStore } from './llm-blob-store'
import { LlmGatewayClient, LlmGatewayError } from './llm-gateway.client'
import { compactCompletionForState } from './llm-spill'
import { LlmStepError, LlmStepRequest } from './llm-step.types'
import { WakeOutcome, wakeParkedLlmJob } from './llm-wake'

const DEFAULT_MAX_ATTEMPTS = 3
// Completions serializing above this go to object storage; only a preview + ref lands in state.
const DEFAULT_SPILL_THRESHOLD_BYTES = 8192

const realSleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))

// Orchestrates one LLM request end to end, independent of Kafka/consumer plumbing so it can be
// tested directly: call the gateway (with bounded retry on retriable failures), spill an oversized
// completion to object storage, then wake the parked job by id with the completion (or a ref to it),
// or a terminal error. The wake is idempotent against redelivery via the (jobId, actionId, nonce)
// key and the `status = 'available'` guard.
export async function executeLlmRequest(args: {
    request: LlmStepRequest
    gatewayClient: LlmGatewayClient
    pool: Pick<Pool, 'connect'>
    // When set, oversized completions are spilled here and only a reference is written to state.
    blobStore?: LlmBlobStore
    spillThresholdBytes?: number
    maxAttempts?: number
    sleep?: (ms: number) => Promise<void>
}): Promise<{ outcome: WakeOutcome; error?: LlmStepError }> {
    const { request, gatewayClient, pool, blobStore } = args
    const maxAttempts = args.maxAttempts ?? DEFAULT_MAX_ATTEMPTS
    const spillThresholdBytes = args.spillThresholdBytes ?? DEFAULT_SPILL_THRESHOLD_BYTES
    const sleep = args.sleep ?? realSleep
    const idempotencyKey = `${request.jobId}:${request.actionId}:${request.nonce}`

    let lastError: LlmStepError | undefined
    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
        try {
            const rawCompletion = await gatewayClient.complete(request, { idempotencyKey })
            const completion = blobStore
                ? await compactCompletionForState({
                      completion: rawCompletion,
                      request,
                      blobStore,
                      thresholdBytes: spillThresholdBytes,
                  })
                : rawCompletion
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
