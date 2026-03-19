import { PluginEvent } from '~/plugin-scaffold'
import { ISOTimestamp, Team } from '~/types'
import { logger } from '~/utils/logger'
import { invalidTimestampCounter } from '~/worker/ingestion/event-pipeline/metrics'
import { parseEventTimestamp } from '~/worker/ingestion/timestamps'

import { BatchProcessingStep } from '../pipelines/base-batch-pipeline'
import { PipelineWarning } from '../pipelines/pipeline.interface'
import { PipelineResult, drop, ok } from '../pipelines/results'
import { CymbalClient } from './cymbal/client'
import { CymbalRequest, CymbalResponse } from './cymbal/types'

export interface CymbalProcessingInput {
    event: PluginEvent
    team: Team
}

/**
 * Validates and normalizes the event timestamp.
 * Returns the validated ISO timestamp and any warnings from invalid timestamps.
 */
function validateEventTimestamp(event: PluginEvent): { timestamp: ISOTimestamp; warnings: PipelineWarning[] } {
    const warnings: PipelineWarning[] = []
    const invalidTimestampCallback = function (type: string, details: Record<string, any>) {
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
 * Extracts ingestion warnings from Cymbal's response.
 *
 * When Cymbal encounters processing errors (e.g., missing sourcemaps, invalid properties,
 * empty exception list), it attaches them to $cymbal_errors and still returns the event.
 * We convert these to ingestion warnings so users can see them in the PostHog UI.
 */
function getCymbalProcessingWarnings(response: CymbalResponse, eventUuid: string): PipelineWarning[] {
    const cymbalErrors = response.properties.$cymbal_errors
    if (!Array.isArray(cymbalErrors) || cymbalErrors.length === 0) {
        return []
    }

    return [
        {
            type: 'error_tracking_exception_processing_errors',
            details: {
                eventUuid,
                errors: cymbalErrors,
            },
            key: eventUuid, // Debounce by event UUID
        },
    ]
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
 */
export function createCymbalProcessingStep<T extends CymbalProcessingInput>(
    cymbalClient: CymbalClient
): BatchProcessingStep<T, T> {
    return async function cymbalProcessingStep(inputs: T[]): Promise<PipelineResult<T>[]> {
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

        // Build requests for all inputs - Cymbal expects AnyEvent format
        const requests: CymbalRequest[] = validatedInputs.map(({ input, timestamp }) => ({
            uuid: input.event.uuid,
            event: input.event.event,
            team_id: input.team.id,
            timestamp,
            properties: input.event.properties ?? {},
        }))

        try {
            const responses = await cymbalClient.processExceptions(requests)

            // Map responses back to results, maintaining 1:1 correspondence
            return responses.map((response, index) => {
                const { input, warnings: timestampWarnings } = validatedInputs[index]

                // Null response means the event should be dropped (suppressed)
                if (!response) {
                    logger.debug('🔇', 'cymbal_event_suppressed', {
                        eventUuid: input.event.uuid,
                        teamId: input.team.id,
                    })
                    return drop('suppressed')
                }

                // Replace event properties with Cymbal's processed properties.
                // Cymbal returns the full properties object with $exception_list, $exception_fingerprint, etc.
                // We mutate the event directly since it's not used after this step.
                input.event.properties = response.properties

                // Combine timestamp validation warnings with Cymbal processing warnings
                const cymbalWarnings = getCymbalProcessingWarnings(response, input.event.uuid)
                const warnings = [...timestampWarnings, ...cymbalWarnings]

                return ok({ ...input, event: input.event }, [], warnings)
            })
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
