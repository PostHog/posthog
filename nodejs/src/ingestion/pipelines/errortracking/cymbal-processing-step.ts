import { Message } from 'node-rdkafka'

import { OVERFLOW_OUTPUT, OverflowOutput } from '~/common/outputs'
import { logger } from '~/common/utils/logger'
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

import { CymbalClient } from './cymbal/client'
import { CymbalResponse } from './cymbal/types'

export interface CymbalProcessingInput {
    event: PluginEvent
    team: Team
    /** Byte size of the original Kafka message, used to estimate HTTP payload size. */
    messageBytes?: number
    /** The original Kafka message, whose headers count the attempts made on the overflow lane. */
    message?: Pick<Message, 'headers'>
}

export interface CymbalRetryOptions {
    overflowMode: IngestionOverflowMode
    preservePartitionLocality: boolean
}

export const CYMBAL_RETRY_ATTEMPTS_HEADER = 'cymbal-retry-attempts'

/** Attempts the overflow lane makes on an event that Cymbal asks to retry, before the DLQ. */
export const CYMBAL_MAX_OVERFLOW_ATTEMPTS = 3

function previousOverflowAttempts(message: Pick<Message, 'headers'> | undefined): number {
    for (const header of message?.headers ?? []) {
        const value = header[CYMBAL_RETRY_ATTEMPTS_HEADER]
        if (value !== undefined) {
            const attempts = Number.parseInt(value.toString(), 10)
            return Number.isNaN(attempts) ? 0 : attempts
        }
    }
    return 0
}

/** Returns `undefined` when the event has no further attempt to make, which sends it to the DLQ. */
function retryOnOverflow<T>(
    { overflowMode, preservePartitionLocality }: CymbalRetryOptions,
    message: Pick<Message, 'headers'> | undefined,
    warnings: PipelineWarning[]
): PipelineResult<T, OverflowOutput> | undefined {
    if (overflowMode === 'disabled') {
        return undefined
    }
    // Only the overflow lane counts attempts, because the main lane always hands the event over.
    const attempts = overflowMode === 'consume' ? previousOverflowAttempts(message) + 1 : 0
    if (attempts >= CYMBAL_MAX_OVERFLOW_ATTEMPTS) {
        return undefined
    }
    return redirect('cymbal_item_retry', OVERFLOW_OUTPUT, {
        preserveKey: preservePartitionLocality,
        warnings,
        headers: attempts > 0 ? { [CYMBAL_RETRY_ATTEMPTS_HEADER]: String(attempts) } : undefined,
    })
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
 * An event that Cymbal asks to retry gets its next attempt on the overflow lane, so the lane that
 * read it does not wait. The main lane redirects it there. The overflow lane puts it back on its
 * own topic, and sends it to the DLQ after {@link CYMBAL_MAX_OVERFLOW_ATTEMPTS} attempts. A
 * consumer without an overflow lane sends it to the DLQ.
 */
export function createCymbalProcessingStep<T extends CymbalProcessingInput>(
    cymbalClient: CymbalClient,
    retryOptions: CymbalRetryOptions = { overflowMode: 'disabled', preservePartitionLocality: true }
): ChunkProcessingStep<T, T, OverflowOutput> {
    return async function cymbalProcessingStep(inputs: T[]): Promise<PipelineResult<T, OverflowOutput>[]> {
        if (inputs.length === 0) {
            return []
        }

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
            const results = await cymbalClient.processExceptions(items)

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
                (_error, index, warnings) =>
                    retryOnOverflow(retryOptions, validatedInputs[index].input.message, warnings)
            )
        } catch (error) {
            logger.error('❌', 'cymbal_batch_processing_error', {
                error: error instanceof Error ? error.message : String(error),
                batchSize: inputs.length,
            })

            // Throw so Kafka retries the batch. For retriable errors (5xx, timeout, network),
            // this allows automatic recovery when Cymbal comes back. For non-retriable errors
            // (4xx), this indicates a bug in our request building that needs fixing.
            throw error
        }
    }
}
