import { PluginEvent } from '@posthog/plugin-scaffold'
import { EachBatchHandler, Kafka } from 'kafkajs'

import { KAFKA_SESSION_RECORDING_EVENTS, KAFKA_SESSION_RECORDING_EVENTS_DLQ } from '../../config/kafka-topics'
import { PipelineEvent, RawEventMessage } from '../../types'
import { KafkaProducerWrapper } from '../../utils/db/kafka-producer-wrapper'
import { status } from '../../utils/status'
import { createPerformanceEvent, createSessionRecordingEvent } from '../../worker/ingestion/process-event'
import { TeamManager } from '../../worker/ingestion/team-manager'
import { parseEventTimestamp } from '../../worker/ingestion/timestamps'
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

            if (event.event === '$snapshot') {
                await createSessionRecordingEvent(
                    messagePayload.uuid,
                    messagePayload.team_id,
                    event.distinct_id,
                    parseEventTimestamp(event as PluginEvent),
                    event.ip,
                    event.properties || {},
                    producer
                )
            } else if (event.event === '$performance_event') {
                await createPerformanceEvent(
                    messagePayload.uuid,
                    messagePayload.team_id,
                    event.distinct_id,
                    event.properties || {},
                    event.ip,
                    parseEventTimestamp(event as PluginEvent),
                    producer
                )
            }

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
