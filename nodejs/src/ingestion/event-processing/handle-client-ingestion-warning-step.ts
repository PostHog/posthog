import { PluginEvent } from '~/plugin-scaffold'

import { PipelineResult, dlq, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export interface HandleClientIngestionWarningStepInput {
    event: PluginEvent
}

// Warning types that may be requested via $$client_ingestion_warning_type,
// with a validator for the shape their UI renderer depends on. Allowlisted so
// arbitrary client traffic can't emit unrelated or malformed warning types.
const WARNING_TYPE_OVERRIDES: Record<string, (details: Record<string, unknown>) => boolean> = {
    // capture emits this when a snapshot batch exceeds the maximum message
    // size; the renderer needs details.replayRecord.session_id
    replay_message_too_large: (details) => {
        const replayRecord = details.replayRecord
        return isPlainObject(replayRecord) && typeof (replayRecord as Record<string, unknown>).session_id === 'string'
    },
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
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

        const extraDetails = event.properties?.$$client_ingestion_warning_details
        const validatedDetails = isPlainObject(extraDetails) ? extraDetails : {}

        const requestedType = event.properties?.$$client_ingestion_warning_type
        const type =
            typeof requestedType === 'string' && WARNING_TYPE_OVERRIDES[requestedType]?.(validatedDetails)
                ? requestedType
                : 'client_ingestion_warning'

        return ok(
            undefined,
            [],
            [
                {
                    type,
                    details: {
                        ...validatedDetails,
                        eventUuid: event.uuid,
                        event: event.event,
                        distinctId: event.distinct_id,
                        message: event.properties?.$$client_ingestion_warning_message,
                    },
                    alwaysSend: true,
                },
            ]
        )
    }
}
