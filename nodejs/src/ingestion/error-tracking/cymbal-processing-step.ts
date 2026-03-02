import { PluginEvent } from '~/plugin-scaffold'
import { Team } from '~/types'
import { logger } from '~/utils/logger'

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

        // Build requests for all inputs - Cymbal expects AnyEvent format
        const requests: CymbalRequest[] = inputs.map(({ event, team }) => ({
            uuid: event.uuid,
            event: event.event,
            team_id: team.id,
            // event.now is required by PluginEvent type and always set by the parse step,
            // but we add a fallback for defensive programming against malformed events
            timestamp: event.timestamp ?? event.now ?? new Date().toISOString(),
            properties: event.properties ?? {},
        }))

        try {
            const responses = await cymbalClient.processExceptions(requests)

            // Map responses back to results, maintaining 1:1 correspondence
            return responses.map((response, index) => {
                const input = inputs[index]

                // Null response means the event should be dropped (suppressed)
                if (!response) {
                    logger.debug('🔇', 'cymbal_event_suppressed', {
                        eventUuid: input.event.uuid,
                        teamId: input.team.id,
                    })
                    return drop('suppressed')
                }

                // Replace event properties with Cymbal's processed properties
                // Cymbal returns the full properties object with $exception_list, $exception_fingerprint, etc.
                const processedEvent: PluginEvent = {
                    ...input.event,
                    properties: response.properties,
                }

                // Check for processing errors from Cymbal
                const warnings = getCymbalProcessingWarnings(response, input.event.uuid)

                return ok({ ...input, event: processedEvent }, [], warnings)
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
