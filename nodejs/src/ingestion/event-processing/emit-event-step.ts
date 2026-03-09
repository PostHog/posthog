import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'

import { ingestionLagGauge, ingestionLagHistogram } from '../../common/metrics'
import { EventHeaders, ProcessedEvent, RawKafkaEvent, TimestampFormat } from '../../types'
import { safeClickhouseString } from '../../utils/db/utils'
import { castTimestampOrNow, castTimestampToClickhouseFormat } from '../../utils/utils'
import { eventProcessedAndIngestedCounter } from '../../worker/ingestion/event-pipeline/metrics'
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

        for (const { event, output } of eventsToEmit) {
            const { topic, producer } = outputs.resolve(output)
            const serialized = serializeEvent(event)

            // Fire-and-forget: enqueue into rdkafka's buffer without awaiting delivery reports.
            // Errors are surfaced at batch boundary via flushWithErrors() in awaitScheduledWork.
            producer.enqueue({
                topic,
                key: serialized.uuid,
                value: Buffer.from(JSON.stringify(serialized)),
                headers: { productTrack: productTrackHeader(event) },
            })

            eventProcessedAndIngestedCounter.inc()
        }

        return Promise.resolve(ok(undefined))
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
