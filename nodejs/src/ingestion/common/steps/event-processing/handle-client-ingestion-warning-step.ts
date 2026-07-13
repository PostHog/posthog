import { Message } from 'node-rdkafka'

import { IngestionWarningsOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import {
    INGESTION_WARNING_TYPES,
    IngestionWarning,
    IngestionWarningType,
    emitIngestionWarning,
} from '~/ingestion/common/ingestion-warnings'
import { PipelineResult, dlq, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { PluginEvent } from '~/plugin-scaffold'
import { EventHeaders } from '~/types'

import { EmitEventStepOutput, IngestedEventInfo } from './emit-event-step'

export interface HandleClientIngestionWarningStepInput {
    event: PluginEvent
    team: { id: number }
    headers: EventHeaders
    message: Message
}

/**
 * Emits a `client_ingestion_warning` ingestion warning for the event. Mirrors
 * the emit event step's output: the warning produce promise resolves with the
 * ingested event info (or null when the warning could not be produced) so
 * downstream steps can observe when the event has been ingested.
 */
export function createHandleClientIngestionWarningStep<TInput extends HandleClientIngestionWarningStepInput>(
    outputs: IngestionOutputs<IngestionWarningsOutput>
): ProcessingStep<TInput, EmitEventStepOutput> {
    return function handleClientIngestionWarningStep(input: TInput): Promise<PipelineResult<EmitEventStepOutput>> {
        const { event, team, headers, message } = input

        if (event.event !== '$$client_ingestion_warning') {
            return Promise.resolve(
                dlq('unexpected_event_type', new Error(`Expected $$client_ingestion_warning, got ${event.event}`))
            )
        }

        const ingestedInfo: IngestedEventInfo = {
            capturedAt: headers.now,
            topic: message.topic,
            partition: message.partition,
        }

        const ingested = emitIngestionWarning(outputs, team.id, buildWarning(event)).then((emitted) =>
            emitted ? ingestedInfo : null
        )

        return Promise.resolve(ok({ ingested: [ingested] }, [ingested]))
    }
}

/**
 * Build the ingestion warning for a `$$client_ingestion_warning` event.
 *
 * Backend producers that can't resolve token->team (capture) emit a synthetic
 * `$$client_ingestion_warning` event carrying a structured warning type,
 * details, and source in its properties. When present and recognized we
 * preserve them and let the per-(team,type) limiter throttle the warning.
 * Otherwise we fall back to the original client-emitted warning shape.
 */
function buildWarning(event: PluginEvent): IngestionWarning {
    const props = event.properties ?? {}
    const structuredType = props.$$client_ingestion_warning_type

    if (typeof structuredType === 'string' && structuredType in INGESTION_WARNING_TYPES) {
        const detailsIn = (props.$$client_ingestion_warning_details ?? {}) as Record<string, any>
        const { pipelineStep, ...restDetails } = detailsIn
        const source = props.$$client_ingestion_warning_source
        return {
            type: structuredType as IngestionWarningType,
            // Envelope ids are defaults; the producer's own ids (the offending
            // event, not the synthetic warning event) win when supplied.
            details: { eventUuid: event.uuid, distinctId: event.distinct_id, ...restDetails },
            pipelineStep: typeof pipelineStep === 'string' ? pipelineStep : undefined,
            source: typeof source === 'string' ? source : undefined,
            // Deliberately no alwaysSend: the per-(team,type) limiter is the
            // gatekeeper for backend-produced volume.
        }
    }

    return {
        type: 'client_ingestion_warning',
        details: {
            eventUuid: event.uuid,
            event: event.event,
            distinctId: event.distinct_id,
            message: props.$$client_ingestion_warning_message,
        },
        pipelineStep: 'client-emit',
        alwaysSend: true,
    }
}
