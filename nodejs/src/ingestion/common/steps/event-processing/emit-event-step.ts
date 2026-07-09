import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'

import { IngestionWarningsOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { MessageSizeTooLarge } from '~/common/utils/db/error'
import { safeClickhouseString } from '~/common/utils/db/utils'
import { castTimestampOrNow, castTimestampToClickhouseFormat } from '~/common/utils/utils'
import { emitIngestionWarning } from '~/ingestion/common/ingestion-warnings'
import { eventProcessedAndIngestedCounter } from '~/ingestion/common/metrics'
import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { EventHeaders, ProcessedEvent, RawKafkaEvent, TimestampFormat } from '~/types'

export interface EventToEmit<O extends string> {
    event: ProcessedEvent
    output: O
}

export interface EmitEventStepConfig<O extends string> {
    outputs: IngestionOutputs<O | IngestionWarningsOutput>
}

export interface EmitEventStepInput<O extends string> {
    eventsToEmit: EventToEmit<O>[]
    teamId: number
    headers: EventHeaders
    message: Message
}

/**
 * Info about an ingested event, resolved by `ingested` promises once the
 * event has been acked by Kafka.
 */
export interface IngestedEventInfo {
    /** Capture time from the `now` header; undefined when the header is missing. */
    capturedAt?: Date
    /** Topic and partition the event was consumed from. */
    topic: string
    partition: number
}

export interface EmitEventStepOutput {
    /**
     * One promise per emitted event, resolving with the event info once the
     * emission has been acked by Kafka, or with null when the event was not
     * ingested (e.g. rejected as too large). The same promises also flow
     * through side effects for scheduling; this field lets downstream steps
     * (e.g. ingestion lag recording) observe when the events have actually
     * been ingested. Empty when nothing was emitted.
     */
    ingested: Promise<IngestedEventInfo | null>[]
}

export function createEmitEventStep<O extends string, T extends EmitEventStepInput<O>>(
    config: EmitEventStepConfig<O>
): ProcessingStep<T, EmitEventStepOutput> {
    return function emitEventStep(input) {
        const { eventsToEmit, headers, message } = input
        const { outputs } = config

        const ingestedInfo: IngestedEventInfo = {
            capturedAt: headers.now,
            topic: message.topic,
            partition: message.partition,
        }

        const ingested: Promise<IngestedEventInfo | null>[] = []

        for (const { event, output } of eventsToEmit) {
            const serialized = serializeEvent(event)

            // TODO: It's not great that we put the produce outcome in side effects, we should probably await it here
            //       but it might slow the pipeline down. Historically, it has always been like that.
            //       We should investigate this later.
            const emitPromise = outputs
                .produce(output, {
                    key: serialized.uuid,
                    value: Buffer.from(JSON.stringify(serialized)),
                    headers: { productTrack: productTrackHeader(event) },
                    teamId: serialized.team_id,
                })
                .then(() => {
                    eventProcessedAndIngestedCounter.inc()
                    return ingestedInfo
                })
                .catch(async (error) => {
                    // TODO: For now we have to live with the ingestion warning happening here
                    //       Once the batch pipelines support warnings, we'll put it in the result
                    // Some messages end up significantly larger than the original
                    // after plugin processing, person & group enrichment, etc.
                    if (error instanceof MessageSizeTooLarge) {
                        await emitIngestionWarning(outputs, serialized.team_id, {
                            type: 'message_size_too_large',
                            details: {
                                eventUuid: serialized.uuid,
                                distinctId: serialized.distinct_id,
                                personId: serialized.person_id,
                            },
                            pipelineStep: 'emit-event',
                        })
                        // The event was not ingested, so there is no info to resolve with
                        return null
                    } else {
                        throw error
                    }
                })

            ingested.push(emitPromise)
        }

        return Promise.resolve(ok({ ingested }, ingested))
    }
}

export function serializeEvent(event: ProcessedEvent): RawKafkaEvent {
    return {
        uuid: event.uuid,
        event: safeClickhouseString(event.event),
        properties: JSON.stringify(event.properties ?? {}),
        timestamp: castTimestampOrNow(event.timestamp, TimestampFormat.ClickHouse),
        team_id: event.team_id,
        project_id: event.project_id,
        distinct_id: safeClickhouseString(event.distinct_id),
        elements_chain: safeClickhouseString(event.elements_chain),
        created_at: castTimestampOrNow(null, TimestampFormat.ClickHouse),
        captured_at:
            event.captured_at !== null
                ? castTimestampToClickhouseFormat(DateTime.fromJSDate(event.captured_at), TimestampFormat.ClickHouse)
                : null,
        person_id: event.person_id,
        person_properties: JSON.stringify(event.person_properties ?? {}),
        person_created_at: castTimestampOrNow(event.person_created_at, TimestampFormat.ClickHouseSecondPrecision),
        person_mode: event.person_mode,
        ...(event.historical_migration ? { historical_migration: true } : {}),
    }
}

export function productTrackHeader(event: ProcessedEvent): string {
    return event.event.startsWith('$ai_') ? 'llma' : 'general'
}
