import { PluginEvent } from '~/plugin-scaffold'
import { Team } from '~/types'
import { logger } from '~/utils/logger'

import { BatchProcessingStep } from '../pipelines/base-batch-pipeline'
import { PipelineResult, drop, ok } from '../pipelines/results'
import { CymbalClient } from './cymbal/client'
import { CymbalRequest } from './cymbal/types'

export interface CymbalProcessingInput {
    event: PluginEvent
    team: Team
}

/**
 * Creates a batch step that processes exception events through Cymbal.
 * Cymbal handles symbolication, fingerprinting, and issue linking.
 *
 * This is a batch step because Cymbal's API accepts arrays of events,
 * which is more efficient than individual requests.
 *
 * The event properties are expected to already contain:
 * - $exception_list: The exception stack traces
 * - $geoip_*: GeoIP enrichment data (from geoip step)
 * - $group_*: Group mappings (from group type mapping step)
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
            timestamp: event.timestamp ?? event.now,
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

                return ok({ ...input, event: processedEvent })
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
