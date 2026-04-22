import { PluginEvent } from '~/plugin-scaffold'
import { ISOTimestamp, Team } from '~/types'
import { logger } from '~/utils/logger'
import { invalidTimestampCounter } from '~/worker/ingestion/event-pipeline/metrics'
import { parseEventTimestamp } from '~/worker/ingestion/timestamps'

import { BatchRetryStepResult } from '../pipelines/batch-retry'
import { PipelineWarning } from '../pipelines/pipeline.interface'
import { drop, ok } from '../pipelines/results'
import { CymbalClient } from './cymbal/client'
import { CymbalResponse } from './cymbal/types'

export interface CymbalProcessingInput {
    event: PluginEvent
    team: Team
    /** Byte size of the original Kafka message, used to estimate HTTP payload size. */
    messageBytes?: number
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
): (inputs: T[]) => Promise<BatchRetryStepResult<T>[]> {
    return async function cymbalProcessingStep(inputs: T[]): Promise<BatchRetryStepResult<T>[]> {
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

        const results = await cymbalClient.processExceptions(items)

        // Map results back, maintaining 1:1 correspondence
        return results.map((result, index) => {
            const { input, warnings: timestampWarnings } = validatedInputs[index]

            // Cymbal call failed — pass through for the wrapper to retry/overflow
            if (result.status === 'failed') {
                return {
                    status: 'failed' as const,
                    retriable: result.retriable,
                    reason: result.reason,
                }
            }

            // Null response means the event should be dropped (suppressed)
            if (!result.response) {
                logger.debug('🔇', 'cymbal_event_suppressed', {
                    eventUuid: input.event.uuid,
                    teamId: input.team.id,
                })
                return { status: 'success' as const, result: drop('suppressed') }
            }

            // Replace event properties with Cymbal's processed properties.
            input.event.properties = result.response.properties

            // Combine timestamp validation warnings with Cymbal processing warnings
            const cymbalWarnings = getCymbalProcessingWarnings(result.response, input.event.uuid)
            const warnings = [...timestampWarnings, ...cymbalWarnings]

            return { status: 'success' as const, result: ok({ ...input, event: input.event }, [], warnings) }
        })
    }
}
