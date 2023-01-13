import { EachBatchHandler, Kafka } from 'kafkajs'

import {
    KAFKA_CLICKHOUSE_SESSION_RECORDING_EVENTS,
    KAFKA_PERFORMANCE_EVENTS,
    KAFKA_SESSION_RECORDING_EVENTS,
    KAFKA_SESSION_RECORDING_EVENTS_DLQ,
} from '../../config/kafka-topics'
import { PipelineEvent, RawEventMessage, RawSessionRecordingEvent, TimestampFormat } from '../../types'
import { KafkaProducerWrapper } from '../../utils/db/kafka-producer-wrapper'
import { status } from '../../utils/status'
import { castTimestampOrNow } from '../../utils/utils'
import { TeamManager } from '../../worker/ingestion/team-manager'
import { instrumentEachBatch, setupEventHandlers } from './kafka-queue'

export const startSessionRecordingEventsConsumer = async ({
    teamManager,
    kafka,
    producer,
}: {
    teamManager: TeamManager
    kafka: Kafka
    producer: KafkaProducerWrapper
}) => {
    /*
        For Session Recordings we need to prepare the data for ClickHouse.
        Additionally, we process `$performance_event` events which are closely
        tied to session recording events.

        NOTE: it may be safer to also separate processing of
        `$performance_event` but for now we'll keep it in the same consumer.
    */

    const consumer = kafka.consumer({ groupId: 'session-recordings' })
    setupEventHandlers(consumer)

    status.info('🔁', 'Starting session recordings consumer')

    const eachBatch: EachBatchHandler = async ({ batch, heartbeat }) => {
        status.debug('🔁', 'Processing batch', { size: batch.messages.length })
        for (const message of batch.messages) {
            if (!message.value) {
                status.warn('⚠️', 'invalid_message', {
                    reason: 'empty',
                    partition: batch.partition,
                    offset: message.offset,
                })
                await producer.queueMessage({ topic: KAFKA_SESSION_RECORDING_EVENTS_DLQ, messages: [message] })
                continue
            }

            let messagePayload: RawEventMessage
            let event: PipelineEvent

            try {
                // NOTE: we need to parse the JSON for these events because we
                // need to add in the team_id to events, as it is possible due
                // to a drive to remove postgres dependency on the the capture
                // endpoint we may only have `token`.
                messagePayload = JSON.parse(message.value.toString())
                event = JSON.parse(messagePayload.data)
            } catch (error) {
                status.warn('⚠️', 'invalid_message', {
                    reason: 'invalid_json',
                    error: error,
                    partition: batch.partition,
                    offset: message.offset,
                })
                await producer.queueMessage({ topic: KAFKA_SESSION_RECORDING_EVENTS_DLQ, messages: [message] })
                continue
            }

            status.debug('⬆️', 'processing_session_recording', { uuid: messagePayload.uuid })

            if (!messagePayload.team_id && !event.token) {
                status.warn('⚠️', 'invalid_message', {
                    reason: 'no_token',
                    partition: batch.partition,
                    offset: message.offset,
                })
                await producer.queueMessage({ topic: KAFKA_SESSION_RECORDING_EVENTS_DLQ, messages: [message] })
                continue
            }

            const teamId =
                messagePayload.team_id ?? (event.token ? await teamManager.getTeamIdByToken(event.token) : null)

            if (!teamId) {
                status.warn('⚠️', 'invalid_message', {
                    reason: 'team_not_found',
                    partition: batch.partition,
                    offset: message.offset,
                })
                await producer.queueMessage({ topic: KAFKA_SESSION_RECORDING_EVENTS_DLQ, messages: [message] })
                continue
            }

            const timestampString = castTimestampOrNow(event.timestamp!, TimestampFormat.ClickHouse)
            const data: Partial<RawSessionRecordingEvent> = {
                uuid: messagePayload.uuid,
                team_id: messagePayload.team_id!,
                distinct_id: messagePayload.distinct_id,
                session_id: event.properties?.$session_id,
                window_id: event.properties?.$window_id,
                snapshot_data: JSON.stringify(event.properties?.$snapshot_data),
                timestamp: timestampString,
                created_at: timestampString,
            }

            await producer.queueMessage({
                topic:
                    event.event === '$performance_event'
                        ? KAFKA_PERFORMANCE_EVENTS
                        : KAFKA_CLICKHOUSE_SESSION_RECORDING_EVENTS,
                messages: [
                    {
                        value: JSON.stringify(data),
                        key: message.key,
                    },
                ],
            })

            // After processing each message, we need to heartbeat to ensure
            // we don't get kicked out of the group. Note that although we call
            // this for each message, it's actually a no-op if we're not over
            // the heartbeatInterval.
            await heartbeat()
        }

        await producer.flush()

        status.info('✅', 'Processed batch', { size: batch.messages.length })
    }

    await consumer.connect()
    await consumer.subscribe({ topic: KAFKA_SESSION_RECORDING_EVENTS })
    await consumer.run({
        eachBatch: async (payload) => {
            return await instrumentEachBatch(KAFKA_SESSION_RECORDING_EVENTS, eachBatch, payload)
        },
    })

    return consumer
}
