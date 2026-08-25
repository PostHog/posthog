import { Message } from 'node-rdkafka'

import { IngestionWarningsOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import {
    CAPTURE_PRODUCED_WARNING_TYPES,
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
 * details, and source in its properties. When present and one of the types a
 * trusted backend producer actually emits (`CAPTURE_PRODUCED_WARNING_TYPES`)
 * we preserve them and let the per-(team,type) limiter throttle the warning.
 * Otherwise we fall back to the original client-emitted warning shape.
 *
 * These properties ride on a publicly-ingestible event, so they are
 * attacker-controlled — the allowlist (rather than the full ingestion-warning
 * registry) stops a client from impersonating another producer or forging
 * details for a renderer-only type it was never meant to set.
 */
function buildWarning(event: PluginEvent): IngestionWarning {
    const props = event.properties ?? {}
    const structuredType = props.$$client_ingestion_warning_type

    if (
        typeof structuredType === 'string' &&
        CAPTURE_PRODUCED_WARNING_TYPES.has(structuredType as IngestionWarningType)
    ) {
        // Details ride on a publicly-ingestible event, so this is attacker-controlled.
        // Object-rest over a string or array explodes it into one property per
        // character/element (before the limiter runs), so only accept a plain object
        // and drop any other shape (note: typeof null === 'object').
        const rawDetails = props.$$client_ingestion_warning_details
        const detailsIn: Record<string, any> =
            rawDetails !== null && typeof rawDetails === 'object' && !Array.isArray(rawDetails) ? rawDetails : {}
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
