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
}

export interface CymbalRetryOptions {
    overflowMode: IngestionOverflowMode
    preservePartitionLocality: boolean
}

/**
 * Returns `undefined`, which sends the event to the DLQ, unless this lane redirects to an overflow
 * lane. The overflow lane cannot send an event further, because it has no overflow topic of its own.
 */
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
 * An event that Cymbal asks to retry gets its next attempt on the overflow lane, so the main lane
 * does not wait for it. The overflow lane, and a consumer without an overflow lane, send it to the
 * DLQ.
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
                (_error, _index, warnings) => retryOnOverflow(retryOptions, warnings)
            )
        } catch (error) {
            logger.error('❌', 'cymbal_batch_processing_error', {
                error: error instanceof Error ? error.message : String(error),
                batchSize: inputs.length,
            })

            // The client gives each event of a failed request its own result, so this is a DNS
            // failure, a request Cymbal could not take (a network error, 429 or 503), or a bug.
            // Throw so that the retry wrapper retries the whole batch.
            throw error
        }
    }
}
