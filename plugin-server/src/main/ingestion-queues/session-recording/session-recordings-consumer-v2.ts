import { captureException, captureMessage } from '@sentry/node'
import { DateTime } from 'luxon'
import { HighLevelProducer as RdKafkaProducer, Message, NumberNullUndefined } from 'node-rdkafka-acosom'

import { sessionRecordingConsumerConfig } from '../../../config/config'
import {
    KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS,
    KAFKA_SESSION_RECORDING_EVENTS_DLQ,
    KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS,
} from '../../../config/kafka-topics'
import { startBatchConsumer } from '../../../kafka/batch-consumer'
import { createRdConnectionConfigFromEnvVars } from '../../../kafka/config'
import { retryOnDependencyUnavailableError } from '../../../kafka/error-handling'
import { createKafkaProducer, disconnectProducer, flushProducer, produce } from '../../../kafka/producer'
import { PipelineEvent, PluginsServerConfig, RawEventMessage, Team } from '../../../types'
import { status } from '../../../utils/status'
import { createSessionReplayEvent } from '../../../worker/ingestion/process-event'
import { TeamManager } from '../../../worker/ingestion/team-manager'
import { eventDroppedCounter } from '../metrics'

const groupId = 'session-recordings-replay-events'
const sessionTimeout = 30000
const fetchBatchSize = 500

export const startSessionRecordingEventsConsumerV2 = async ({
    teamManager,
    serverConfig,
}: {
    teamManager: TeamManager
    serverConfig: PluginsServerConfig
}) => {
    /*
        For Session Recordings we need to prepare the data for ClickHouse.
        Additionally, we process `$performance_event` events which are closely
        tied to session recording events.

        We use the node-rdkafka library for handling consumption and production
        from Kafka. Note that this is different from the other consumers as this
        is a test bed for consumer improvements, which should be ported to the
        other consumers.

        We consume batches of messages, process these to completion, including
        getting acknowledgements that the messages have been pushed to Kafka,
        then commit the offsets of the messages we have processed. We do this
        instead of going completely stream happy just to keep the complexity
        low. We may well move this ingester to a different framework
        specifically for stream processing so no need to put too much work into
        this.
    */

    const recordingsServerConfig = sessionRecordingConsumerConfig(serverConfig)

    status.info('🔁', 'Starting session recordings consumer')

    // We currently produce to the main kafka as this is the one connected to ClickHouse
    const producer = await createKafkaProducer(createRdConnectionConfigFromEnvVars(serverConfig))

    const eachBatchWithContext = eachBatch({
        teamManager,
        producer,
    })

    // Create a node-rdkafka consumer that fetches batches of messages, runs
    // eachBatchWithContext, then commits offsets for the batch.
    const consumer = await startBatchConsumer({
        // We consume from the recording Kafka cluster.
        connectionConfig: createRdConnectionConfigFromEnvVars(recordingsServerConfig),
        groupId,
        topic: KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS,
        sessionTimeout,
        fetchBatchSize,
        consumerMaxBytes: serverConfig.KAFKA_CONSUMPTION_MAX_BYTES,
        consumerMaxBytesPerPartition: serverConfig.KAFKA_CONSUMPTION_MAX_BYTES_PER_PARTITION,
        consumerMaxWaitMs: serverConfig.KAFKA_CONSUMPTION_MAX_WAIT_MS,
        consumerErrorBackoffMs: serverConfig.KAFKA_CONSUMPTION_ERROR_BACKOFF_MS,
        batchingTimeoutMs: serverConfig.KAFKA_CONSUMPTION_BATCHING_TIMEOUT_MS,
        eachBatch: eachBatchWithContext,
    })

    // Make sure to disconnect the producer after we've finished consuming.
    consumer.join().finally(async () => {
        await disconnectProducer(producer)
    })

    return consumer
}

export const eachBatch =
    ({ teamManager, producer }: { teamManager: TeamManager; producer: RdKafkaProducer }) =>
    async (messages: Message[]) => {
        const pendingProduceRequests: Promise<NumberNullUndefined>[] = []

        for (const message of messages) {
            const results = await retryOnDependencyUnavailableError(() =>
                eachMessage({ teamManager, producer, message })
            )
            if (results) {
                pendingProduceRequests.push(...results)
            }
        }

        // On each loop, we flush the producer to ensure that all messages
        // are sent to Kafka.
        try {
            await flushProducer(producer)
        } catch (error) {
            // Rather than handling errors from flush, we instead handle
            // errors per produce request, which gives us a little more
            // flexibility in terms of deciding if it is a terminal
            // error or not.
        }

        // We wait on all the produce requests to complete. After the
        // flush they should all have been resolved/rejected already. If
        // we get an intermittent error, such as a Kafka broker being
        // unavailable, we will throw. We are relying on the Producer
        // already having handled retries internally.
        for (const produceRequest of pendingProduceRequests) {
            try {
                await produceRequest
            } catch (error) {
                status.error('🔁', 'main_loop_error', { error })

                if (error?.isRetriable) {
                    // We assume the if the error is retriable, then we
                    // are probably in a state where e.g. Kafka is down
                    // temporarily and we would rather simply throw and
                    // have the process restarted.
                    throw error
                }
            }
        }
    }

const eachMessage = async ({
    message,
    teamManager,
    producer,
}: {
    teamManager: TeamManager
    producer: RdKafkaProducer
    message: Message
}) => {
    const warn = (text: string, labels: Record<string, any> = {}) =>
        status.warn('⚠️', text, {
            offset: message.offset,
            partition: message.partition,
            ...labels,
        })

    const dlq = (text: string, labels: Record<string, any> = {}) => {
        if (!message.value || !message.timestamp) {
            warn(text, {
                ...labels,
            })
            return [
                produce({
                    producer,
                    topic: KAFKA_SESSION_RECORDING_EVENTS_DLQ,
                    value: message.value,
                    key: message.key ? Buffer.from(message.key) : null,
                }),
            ]
        }
    }

    const drop = (reason: string, labels: Record<string, any> = {}) => {
        if (!message.value || !message.timestamp) {
            eventDroppedCounter
                .labels({
                    event_type: 'session_recordings',
                    drop_cause: reason,
                })
                .inc()

            warn(reason, {
                reason,
                ...labels,
            })
        }
    }

    // For each message, we:
    //
    //  1. Check that the message is valid. If not, send it to the DLQ.
    //  2. Parse the message and extract the event.
    //  3. Get the associated team for the event.
    //  4. Convert the event to something we can insert into ClickHouse.

    if (!message.value || !message.timestamp) {
        return dlq('invalid_message')
    }

    let messagePayload: RawEventMessage
    let event: PipelineEvent

    try {
        messagePayload = JSON.parse(message.value.toString())
        event = JSON.parse(messagePayload.data)
    } catch (error) {
        return dlq('invalid_message', { reason: 'invalid_json', error })
    }

    status.debug('⬆️', 'processing_session_recording', { uuid: messagePayload.uuid })

    if (messagePayload.team_id == null && !messagePayload.token) {
        eventDroppedCounter
            .labels({
                event_type: 'session_recordings',
                drop_cause: 'no_token',
            })
            .inc()
        warn('invalid_message', {
            reason: 'no_token',
        })
        return
    }

    let team: Team | null = null

    if (messagePayload.team_id != null) {
        team = await teamManager.fetchTeam(messagePayload.team_id)
    } else if (messagePayload.token) {
        team = await teamManager.getTeamByToken(messagePayload.token)
    }

    if (team == null) {
        return drop('invalid_token')
    }

    if (!team.session_recording_opt_in) {
        return drop('disabled')
    }

    if (event.event !== '$snapshot_items') {
        return drop('invalid_event_type')
    }

    if (event.properties?.['$snapshot_consumer'] !== 'v2') {
        return drop('invalid_event_type')
    }

    try {
        const replayRecord = createSessionReplayEvent(
            messagePayload.uuid,
            team.id,
            messagePayload.distinct_id,
            event.properties || {}
        )

        try {
            // the replay record timestamp has to be valid and be within a reasonable diff from now
            if (replayRecord !== null) {
                const asDate = DateTime.fromSQL(replayRecord.first_timestamp)
                if (!asDate.isValid || Math.abs(asDate.diffNow('months').months) >= 0.99) {
                    captureMessage(
                        `Invalid replay record timestamp: ${replayRecord.first_timestamp} for event ${messagePayload.uuid}`,
                        {
                            extra: {
                                replayRecord,
                                uuid: replayRecord.uuid,
                                timestamp: replayRecord.first_timestamp,
                            },
                            tags: {
                                team: team.id,
                                session_id: replayRecord.session_id,
                            },
                        }
                    )

                    return drop('invalid_timestamp')
                }
            }
        } catch (e) {
            captureException(e, {
                extra: {
                    replayRecord,
                },
                tags: {
                    team: team.id,
                    session_id: replayRecord.session_id,
                },
            })

            return drop('session_replay_summarizer_error', { error: e })
        }

        return [
            produce({
                producer,
                topic: KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS,
                value: Buffer.from(JSON.stringify(replayRecord)),
                key: message.key ? Buffer.from(message.key) : null,
            }),
        ]
    } catch (error) {
        status.error('⚠️', 'processing_error', {
            eventId: event.uuid,
            error: error,
        })
    }
}
