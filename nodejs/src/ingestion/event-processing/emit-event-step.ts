import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'

import { ingestionLagGauge, ingestionLagHistogram } from '../../common/metrics'
import { EventHeaders, ProcessedEvent, RawKafkaEvent, TimestampFormat } from '../../types'
import { MessageSizeTooLarge } from '../../utils/db/error'
import { safeClickhouseString } from '../../utils/db/utils'
import { castTimestampOrNow, castTimestampToClickhouseFormat } from '../../utils/utils'
import { eventProcessedAndIngestedCounter } from '../../worker/ingestion/event-pipeline/metrics'
import { captureIngestionWarning } from '../../worker/ingestion/utils'
import { ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'
import { IngestionOutputs } from './ingestion-outputs'

export interface EventToEmit<O extends string> {
    event: ProcessedEvent
    output: O
}

export interface EmitEventStepConfig<O extends string> {
    outputs: IngestionOutputs<O>
    groupId: string
}

export interface EmitEventStepInput<O extends string> {
    eventsToEmit: EventToEmit<O>[]
    teamId: number
    headers: EventHeaders
    message: Message
}

export function createEmitEventStep<O extends string, T extends EmitEventStepInput<O>>(
    config: EmitEventStepConfig<O>
): ProcessingStep<T, void> {
    return function emitEventStep(input) {
        const { eventsToEmit, headers, message } = input
        const { outputs, groupId } = config

        // Record ingestion lag metric if we have the required data
        if (headers?.now && message?.topic !== undefined && message?.partition !== undefined) {
            const lag = Date.now() - headers.now.getTime()
            ingestionLagGauge.labels({ topic: message.topic, partition: String(message.partition), groupId }).set(lag)
            ingestionLagHistogram.labels({ groupId, partition: String(message.partition) }).observe(lag)
        }

        const sideEffects: Promise<void>[] = []

        for (const { event, output } of eventsToEmit) {
            const { topic, producer } = outputs.resolve(output)
            const serialized = serializeEvent(event)

            // TODO: It's not great that we put the produce outcome in side effects, we should probably await it here
            //       but it might slow the pipeline down. Historically, it has always been like that.
            //       We should investigate this later.
            const emitPromise = producer
                .produce({
                    topic,
                    key: serialized.uuid,
                    value: Buffer.from(JSON.stringify(serialized)),
                    headers: { productTrack: productTrackHeader(event) },
                })
                .then((result) => {
                    eventProcessedAndIngestedCounter.inc()
                    return result
                })
                .catch(async (error) => {
                    // TODO: For now we have to live with the ingestion warning happening here
                    //       Once the batch pipelines support warnings, we'll put it in the result
                    // Some messages end up significantly larger than the original
                    // after plugin processing, person & group enrichment, etc.
                    if (error instanceof MessageSizeTooLarge) {
                        await captureIngestionWarning(producer, serialized.team_id, 'message_size_too_large', {
                            eventUuid: serialized.uuid,
                            distinctId: serialized.distinct_id,
                        })
                    } else {
                        throw error
                    }
                })

            sideEffects.push(emitPromise)
        }

        return Promise.resolve(ok(undefined, sideEffects))
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
