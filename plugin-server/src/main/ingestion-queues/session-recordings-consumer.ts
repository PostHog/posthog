import { PluginEvent } from '@posthog/plugin-scaffold'
import { EachBatchPayload, Kafka } from 'kafkajs'
import { exponentialBuckets, Histogram } from 'prom-client'

import { KAFKA_SESSION_RECORDING_EVENTS, KAFKA_SESSION_RECORDING_EVENTS_DLQ } from '../../config/kafka-topics'
import { PipelineEvent, RawEventMessage, Team } from '../../types'
import { DependencyUnavailableError } from '../../utils/db/error'
import { KafkaProducerWrapper } from '../../utils/db/kafka-producer-wrapper'
import { status } from '../../utils/status'
import { createPerformanceEvent, createSessionRecordingEvent } from '../../worker/ingestion/process-event'
import { TeamManager } from '../../worker/ingestion/team-manager'
import { parseEventTimestamp } from '../../worker/ingestion/timestamps'
import { instrumentEachBatch, setupEventHandlers } from './kafka-queue'
import { eventDroppedCounter, latestOffsetTimestampGauge } from './metrics'

export const startSessionRecordingEventsConsumer = async ({
    teamManager,
    kafka,
    partitionsConsumedConcurrently = 5,
}: {
    teamManager: TeamManager
    kafka: Kafka
    partitionsConsumedConcurrently: number
}) => {
    /*
        For Session Recordings we need to prepare the data for ClickHouse.
        Additionally, we process `$performance_event` events which are closely
        tied to session recording events.

        NOTE: it may be safer to also separate processing of
        `$performance_event` but for now we'll keep it in the same consumer.
    */

    // We use our own producer as we want to ensure that we don't have out of
    // band calls to the `flush` method via the KAFKA_FLUSH_FREQUENCY_MS option.
    // This ensures that we can handle Kafka Producer errors within the body of
    // the Kafka consumer handler.
    const producer = kafka.producer()
    await producer.connect()
    const producerWrapper = new KafkaProducerWrapper(producer, undefined, { KAFKA_FLUSH_FREQUENCY_MS: 0 } as any)

    const groupId = 'session-recordings'
    const sessionTimeout = 30000
    const consumer = kafka.consumer({ groupId: groupId, sessionTimeout: sessionTimeout })
    setupEventHandlers(consumer)

    status.info('🔁', 'Starting session recordings consumer')

    await consumer.connect()
    await consumer.subscribe({ topic: KAFKA_SESSION_RECORDING_EVENTS })
    await consumer.run({
        partitionsConsumedConcurrently,
        eachBatch: async (payload) => {
            return await instrumentEachBatch(
                KAFKA_SESSION_RECORDING_EVENTS,
                eachBatch({ producer: producerWrapper, teamManager, groupId }),
                payload
            )
        },
    })

    // Subscribe to the heatbeat event to track when the consumer has last
    // successfully consumed a message. This is used to determine if the
    // consumer is healthy.
    const { HEARTBEAT } = consumer.events
    let lastHeartbeat: number = Date.now()
    consumer.on(HEARTBEAT, ({ timestamp }) => (lastHeartbeat = timestamp))

    const isHealthy = async () => {
        // Consumer has heartbeat within the session timeout, so it is healthy.
        if (Date.now() - lastHeartbeat < sessionTimeout) {
            return true
        }

        // Consumer has not heartbeat, but maybe it's because the group is
        // currently rebalancing.
        try {
            const { state } = await consumer.describeGroup()

            return ['CompletingRebalance', 'PreparingRebalance'].includes(state)
        } catch (error) {
            return false
        }
    }

    return { consumer, isHealthy }
}

export const eachBatch =
    ({
        producer,
        teamManager,
        groupId,
    }: {
        producer: KafkaProducerWrapper
        teamManager: TeamManager
        groupId: string
    }) =>
    async ({ batch, heartbeat }: Pick<EachBatchPayload, 'batch' | 'heartbeat'>) => {
        status.debug('🔁', 'Processing batch', { size: batch.messages.length })

        consumerBatchSize
            .labels({
                topic: batch.topic,
                groupId,
            })
            .observe(batch.messages.length)

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

            consumedMessageSizeBytes
                .labels({
                    topic: batch.topic,
                    groupId,
                    messageType: event.event,
                })
                .observe(message.value.length)

            if (messagePayload.team_id == null && !messagePayload.token) {
                eventDroppedCounter
                    .labels({
                        event_type: 'session_recordings',
                        drop_cause: 'no_token',
                    })
                    .inc()
                status.warn('⚠️', 'invalid_message', {
                    reason: 'no_token',
                    partition: batch.partition,
                    offset: message.offset,
                })
                continue
            }

            let team: Team | null = null

            if (messagePayload.team_id != null) {
                team = await teamManager.fetchTeam(messagePayload.team_id)
            } else if (messagePayload.token) {
                team = await teamManager.getTeamByToken(messagePayload.token)
            }

            if (team == null) {
                eventDroppedCounter
                    .labels({
                        event_type: 'session_recordings',
                        drop_cause: 'invalid_token',
                    })
                    .inc()
                status.warn('⚠️', 'invalid_message', {
                    reason: 'team_not_found',
                    partition: batch.partition,
                    offset: message.offset,
                })
                continue
            }

            if (team.session_recording_opt_in) {
                try {
                    if (event.event === '$snapshot') {
                        await createSessionRecordingEvent(
                            messagePayload.uuid,
                            team.id,
                            messagePayload.distinct_id,
                            parseEventTimestamp(event as PluginEvent),
                            event.ip,
                            event.properties || {},
                            producer
                        )
                    } else if (event.event === '$performance_event') {
                        await createPerformanceEvent(
                            messagePayload.uuid,
                            team.id,
                            messagePayload.distinct_id,
                            event.properties || {},
                            event.ip,
                            parseEventTimestamp(event as PluginEvent),
                            producer
                        )
                    }
                } catch (error) {
                    status.error('⚠️', 'processing_error', {
                        eventId: event.uuid,
                        error: error,
                    })

                    if (error instanceof DependencyUnavailableError) {
                        // If it's an error that is transient, we want to
                        // initiate the KafkaJS retry logic, which kicks in when
                        // we throw.
                        throw error
                    }

                    // On non-retriable errors, e.g. perhaps the produced message
                    // was too large, push the original message to the DLQ. This
                    // message should be as the original so we _should_ be able to
                    // produce it successfully.
                    // TODO: it is not guaranteed that only this message is the one
                    // that failed to be produced. We will already be in the
                    // situation with the existing implementation so I will leave as
                    // is for now. An improvement would be to keep track of the
                    // messages that we failed to produce and send them all to the
                    // DLQ.
                    await producer.queueMessage({ topic: KAFKA_SESSION_RECORDING_EVENTS_DLQ, messages: [message] })
                }
            }

            // After processing each message, we need to heartbeat to ensure
            // we don't get kicked out of the group. Note that although we call
            // this for each message, it's actually a no-op if we're not over
            // the `heartbeatInterval`.
            await heartbeat()
        }

        try {
            // We want to make sure that we have flushed the previous batch
            // before we complete the batch handling, such that we do not commit
            // messages if Kafka production fails for a retriable reason.
            await producer.flush()
        } catch (error) {
            status.error('⚠️', 'flush_error', { error: error, topic: batch.topic, partition: batch.partition })

            if (error instanceof DependencyUnavailableError) {
                throw error
            }

            // NOTE: for errors coming from `flush` we don't have much by the
            // way of options at the moment for e.g. DLQing these messages as we
            // don't know which they were.
            // TODO: handle DLQ/retrying on flush errors. At the moment we don't
            // know which messages failed as a result of this flush error. For
            // now I am going to just going to rely on the producer wrapper
            // having sent a Sentry exception, but we should ideally send these
            // to the DLQ.
        }

        const lastBatchMessage = batch.messages[batch.messages.length - 1]
        latestOffsetTimestampGauge
            .labels({ partition: batch.partition, topic: batch.topic, groupId })
            .set(Number.parseInt(lastBatchMessage.timestamp))

        status.debug('✅', 'Processed batch', { size: batch.messages.length })
    }

const consumerBatchSize = new Histogram({
    name: 'consumed_batch_size',
    help: 'Size of the batch fetched by the consumer',
    labelNames: ['topic', 'groupId'],
    buckets: exponentialBuckets(1, 3, 5),
})

const consumedMessageSizeBytes = new Histogram({
    name: 'consumed_message_size_bytes',
    help: 'Size of consumed message value in bytes',
    labelNames: ['topic', 'groupId', 'messageType'],
    buckets: exponentialBuckets(1, 8, 4).map((bucket) => bucket * 1024),
})
