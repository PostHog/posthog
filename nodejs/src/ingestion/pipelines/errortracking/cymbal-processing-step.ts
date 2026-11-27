import { Counter } from 'prom-client'

import { OVERFLOW_OUTPUT, OverflowOutput } from '~/common/outputs'
import { logger } from '~/common/utils/logger'
import { sleep } from '~/common/utils/utils'
import { IngestionWarningType } from '~/ingestion/common/ingestion-warnings'
import { invalidTimestampCounter } from '~/ingestion/common/metrics'
import { toPipelineResults } from '~/ingestion/common/service-response'
import { parseEventTimestamp } from '~/ingestion/common/timestamps'
import { IngestionOverflowMode } from '~/ingestion/config'
import { ChunkProcessingStep } from '~/ingestion/framework/base-chunk-pipeline'
import { PipelineWarning } from '~/ingestion/framework/pipeline.interface'
import { PipelineResult, ok, redirect } from '~/ingestion/framework/results'
import { PluginEvent } from '~/plugin-scaffold'
import { ISOTimestamp, Team } from '~/types'

import { CYMBAL_UNAVAILABLE_CODE, CymbalClient, CymbalError, CymbalResult } from './cymbal/client'
import { CymbalRequest, CymbalResponse } from './cymbal/types'

export interface CymbalProcessingInput {
    event: PluginEvent
    team: Team
    /** Byte size of the original Kafka message, used to estimate HTTP payload size. */
    messageBytes?: number
}

export interface CymbalRetryOptions {
    overflowMode: IngestionOverflowMode
    preservePartitionLocality: boolean
    /** See ERROR_TRACKING_CYMBAL_RETRY_SOFT_DEADLINE_MS. */
    inPlaceRetrySoftDeadlineMs: number
}

/** The wait before each in-place retry round. Its length is the maximum number of rounds. */
const IN_PLACE_RETRY_DELAYS_MS = [1_000, 3_000, 9_000]

/** Each wait is shortened by a random part of up to this fraction, so pods do not resend in step. */
const IN_PLACE_RETRY_JITTER = 0.5

/** Cymbal answers 429 above a fixed number of requests in flight per pod. */
const IN_PLACE_RETRY_CONCURRENCY = 10

const cymbalInPlaceRetries = new Counter({
    name: 'error_tracking_cymbal_in_place_retries_total',
    help: 'Events resent to Cymbal on their own after a retry result, by the result of the resend',
    labelNames: ['result'],
})

/**
 * Resends each event that asks to retry in its own request, after a growing wait, until no event
 * asks or the soft deadline passes. Returns the latest result of every event.
 */
async function retryInPlace(
    cymbalClient: CymbalClient,
    items: { request: CymbalRequest; estimatedSize: number }[],
    results: CymbalResult[],
    softDeadlineMs: number,
    startedAt: number
): Promise<CymbalResult[]> {
    const deadline = startedAt + softDeadlineMs
    const latest = [...results]
    for (const delayMs of IN_PLACE_RETRY_DELAYS_MS) {
        const pending = latest.flatMap((result, index) => (result.result === 'retry' ? [index] : []))
        const waitMs = delayMs * (1 - IN_PLACE_RETRY_JITTER * Math.random())
        if (pending.length === 0 || Date.now() + waitMs > deadline) {
            break
        }
        await sleep(waitMs)
        const retried = await cymbalClient.processEachException(
            pending.map((index) => items[index]),
            { concurrency: IN_PLACE_RETRY_CONCURRENCY, startBefore: deadline }
        )
        pending.forEach((itemIndex, retriedIndex) => {
            const result = retried[retriedIndex]
            if (result) {
                latest[itemIndex] = result
                cymbalInPlaceRetries.labels({ result: result.result }).inc()
            }
        })
    }
    return latest
}

/**
 * The events are not at fault when Cymbal could not take an event's last resend, or when every
 * event still asks to retry, because then Cymbal or one of its dependencies is down. A lane that
 * cannot redirect then retries the whole batch instead of sending the events to the DLQ.
 */
function cymbalUnavailableError(results: CymbalResult[]): CymbalError | undefined {
    const retries = results.filter((result) => result.result === 'retry')
    const notTaken = retries.filter((result) => result.error.code === CYMBAL_UNAVAILABLE_CODE)
    if (notTaken.length === 0 && retries.length < results.length) {
        return undefined
    }
    return new CymbalError(
        `Cymbal is unavailable: ${retries.length} of ${results.length} events ask to retry, ${notTaken.length} not taken`,
        true
    )
}

/** Returns `undefined`, which sends the event to the DLQ, unless this lane redirects to an overflow lane. */
function retryOnOverflow<T>(
    { overflowMode, preservePartitionLocality }: CymbalRetryOptions,
    warnings: PipelineWarning[]
): PipelineResult<T, OverflowOutput> | undefined {
    if (overflowMode !== 'redirect') {
        return undefined
    }
    return redirect('cymbal_item_retry', OVERFLOW_OUTPUT, { preserveKey: preservePartitionLocality, warnings })
}

/**
 * Validates and normalizes the event timestamp.
 * Returns the validated ISO timestamp and any warnings from invalid timestamps.
 */
function validateEventTimestamp(event: PluginEvent): { timestamp: ISOTimestamp; warnings: PipelineWarning[] } {
    const warnings: PipelineWarning[] = []
    const invalidTimestampCallback = function (type: IngestionWarningType, details: Record<string, any>) {
        invalidTimestampCounter.labels(type).inc()
        warnings.push({ type, details })
    }

    const parsedTimestamp = parseEventTimestamp(event, invalidTimestampCallback)
    return {
        timestamp: parsedTimestamp.toISO() as ISOTimestamp,
        warnings,
    }
}

/**
 * Creates a batch step that processes exception events through Cymbal.
 * Cymbal handles symbolication, fingerprinting, and issue linking.
 *
 * This is a batch step because Cymbal's API accepts arrays of events,
 * which is more efficient than individual requests.
 *
 * Cymbal only needs the raw event data containing $exception_list for
 * symbolication and fingerprinting. Enrichment (person, geoip, groups)
 * happens after Cymbal to reduce payload size and avoid wasted work
 * if events are suppressed.
 *
 * The main lane sends an event that Cymbal asks to retry to the overflow lane. A lane that cannot
 * redirect resends it on its own after a growing wait, and sends it to the DLQ when it still asks
 * to retry after the last round.
 */
export function createCymbalProcessingStep<T extends CymbalProcessingInput>(
    cymbalClient: CymbalClient,
    retryOptions: CymbalRetryOptions = {
        overflowMode: 'disabled',
        preservePartitionLocality: true,
        inPlaceRetrySoftDeadlineMs: 0,
    }
): ChunkProcessingStep<T, T, OverflowOutput> {
    return async function cymbalProcessingStep(inputs: T[]): Promise<PipelineResult<T, OverflowOutput>[]> {
        if (inputs.length === 0) {
            return []
        }
        const startedAt = Date.now()

        // Validate timestamps and collect warnings for each input.
        // This must happen before building Cymbal requests since Cymbal needs valid timestamps.
        const validatedInputs = inputs.map((input) => {
            const { timestamp, warnings } = validateEventTimestamp(input.event)
            // Store validated timestamp back on event for downstream steps
            input.event.timestamp = timestamp
            return { input, timestamp, warnings }
        })

        // Build requests paired with estimated sizes for proactive chunking.
        // Kafka message sizes overestimate the CymbalRequest size (they include
        // headers, distinct_id, and other fields stripped from the request),
        // which is conservative — we split slightly earlier than needed, never too late.
        const items = validatedInputs.map(({ input, timestamp }) => ({
            request: {
                uuid: input.event.uuid,
                event: input.event.event,
                team_id: input.team.id,
                timestamp,
                properties: input.event.properties ?? {},
            },
            estimatedSize: input.messageBytes ?? 0,
        }))

        try {
            let results = await cymbalClient.processExceptions(items)
            if (retryOptions.overflowMode !== 'redirect') {
                results = await retryInPlace(
                    cymbalClient,
                    items,
                    results,
                    retryOptions.inPlaceRetrySoftDeadlineMs,
                    startedAt
                )
                const unavailable = cymbalUnavailableError(results)
                if (unavailable) {
                    throw unavailable
                }
            }

            return toPipelineResults<CymbalResponse, T, OverflowOutput>(
                'cymbal',
                results,
                (response, index, serviceWarnings) => {
                    const { input, warnings: timestampWarnings } = validatedInputs[index]

                    // Replace event properties with Cymbal's processed properties.
                    // Cymbal returns the full properties object with $exception_list, $exception_fingerprint, etc.
                    // We mutate the event directly since it's not used after this step.
                    input.event.properties = response.properties

                    const warnings = [...timestampWarnings, ...serviceWarnings]

                    return ok({ ...input, event: input.event }, [], warnings)
                },
                (_error, _index, warnings) => retryOnOverflow(retryOptions, warnings)
            )
        } catch (error) {
            logger.error('❌', 'cymbal_batch_processing_error', {
                error: error instanceof Error ? error.message : String(error),
                batchSize: inputs.length,
            })

            // Throw so that the retry wrapper retries the whole batch.
            throw error
        }
    }
}
