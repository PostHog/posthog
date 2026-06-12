import { PluginEvent } from '~/plugin-scaffold'

import { PipelineWarning } from '../pipelines/pipeline.interface'
import { PipelineResult, dlq, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export interface HandleClientIngestionWarningStepInput {
    event: PluginEvent
}

// Upper bounds on persisted client-controlled strings, so engineered payloads
// can't grow warning rows or limiter keys.
const MAX_DETAIL_STRING_LENGTH = 200
const MAX_MESSAGE_LENGTH = 1000

interface SanitizedOverride {
    /** The exact details to persist - never the raw client payload. */
    details: Record<string, unknown>
    /** Debounce key for the ingestion warning limiter (scoped by team and type). */
    debounceKey: string
}

// Allowed $$client_ingestion_warning_type overrides. Each sanitizer rebuilds
// the details its UI renderer needs from scratch, or returns null to fall
// back to the generic warning type (clients can send anything here).
const WARNING_TYPE_OVERRIDES: Record<string, (details: Record<string, unknown>) => SanitizedOverride | null> = {
    // emitted by capture when a replay snapshot batch is too large to ingest
    replay_message_too_large: (details) => {
        const replayRecord = isPlainObject(details.replayRecord) ? details.replayRecord : undefined
        const sessionId = boundedString(replayRecord?.session_id)
        const timestamp = boundedString(details.timestamp)
        if (sessionId === null || timestamp === null) {
            return null
        }
        return {
            details: {
                timestamp,
                replayRecord: { session_id: sessionId },
                snapshotBytes: finiteNumber(details.snapshotBytes),
                snapshotItemsCount: finiteNumber(details.snapshotItemsCount),
                lib: boundedString(details.lib) ?? undefined,
            },
            debounceKey: sessionId,
        }
    },
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function boundedString(value: unknown, maxLength: number = MAX_DETAIL_STRING_LENGTH): string | null {
    return typeof value === 'string' && value.length > 0 && value.length <= maxLength ? value : null
}

function finiteNumber(value: unknown): number | undefined {
    return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

export function createHandleClientIngestionWarningStep<
    TInput extends HandleClientIngestionWarningStepInput,
>(): ProcessingStep<TInput, void> {
    return async function handleClientIngestionWarningStep(input: TInput): Promise<PipelineResult<void>> {
        const event = input.event

        if (event.event !== '$$client_ingestion_warning') {
            return Promise.resolve(
                dlq('unexpected_event_type', new Error(`Expected $$client_ingestion_warning, got ${event.event}`))
            )
        }

        const message = event.properties?.$$client_ingestion_warning_message
        const baseDetails = {
            eventUuid: event.uuid,
            event: event.event,
            distinctId: event.distinct_id,
        }

        let warning: PipelineWarning = {
            type: 'client_ingestion_warning',
            details: { ...baseDetails, message },
            alwaysSend: true,
        }

        const requestedType = event.properties?.$$client_ingestion_warning_type
        const extraDetails = event.properties?.$$client_ingestion_warning_details
        if (typeof requestedType === 'string' && isPlainObject(extraDetails)) {
            const override = WARNING_TYPE_OVERRIDES[requestedType]?.(extraDetails)
            if (override) {
                warning = {
                    type: requestedType,
                    details: {
                        ...override.details,
                        ...baseDetails,
                        message: boundedString(message, MAX_MESSAGE_LENGTH) ?? undefined,
                    },
                    key: override.debounceKey,
                }
            }
        }

        return ok(undefined, [], [warning])
    }
}
