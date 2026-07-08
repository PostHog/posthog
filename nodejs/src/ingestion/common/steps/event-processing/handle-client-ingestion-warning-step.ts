import { Message } from 'node-rdkafka'

import { IngestionWarningsOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { emitIngestionWarning } from '~/ingestion/common/ingestion-warnings'
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

        const ingested = emitIngestionWarning(outputs, team.id, {
            type: 'client_ingestion_warning',
            details: {
                eventUuid: event.uuid,
                event: event.event,
                distinctId: event.distinct_id,
                message: event.properties?.$$client_ingestion_warning_message,
            },
            category: 'event',
            severity: 'info',
            pipelineStep: 'client-emit',
            alwaysSend: true,
        }).then((emitted) => (emitted ? ingestedInfo : null))

        return Promise.resolve(ok({ ingested: [ingested] }, [ingested]))
    }
}
