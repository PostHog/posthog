import { captureException } from '@sentry/node'
import { DateTime } from 'luxon'
import { features, librdkafkaVersion, Message } from 'node-rdkafka'

import { sessionRecordingConsumerConfig } from '../../../../config/config'
import {
    KAFKA_CLICKHOUSE_HEATMAP_EVENTS,
    KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS,
} from '../../../../config/kafka-topics'
import { BatchConsumer, startBatchConsumer } from '../../../../kafka/batch-consumer'
import { createRdConnectionConfigFromEnvVars, createRdProducerConfigFromEnvVars } from '../../../../kafka/config'
import { createKafkaProducer, produce } from '../../../../kafka/producer'
import { PipelineEvent, PluginsServerConfig, RawEventMessage, TimestampFormat } from '../../../../types'
import { BackgroundRefresher } from '../../../../utils/background-refresher'
import { KafkaProducerWrapper } from '../../../../utils/db/kafka-producer-wrapper'
import { PostgresRouter } from '../../../../utils/db/postgres'
import { status } from '../../../../utils/status'
import { castTimestampOrNow } from '../../../../utils/utils'
import { fetchTeamTokensWithRecordings } from '../../../../worker/ingestion/team-manager'
import { eventDroppedCounter } from '../../metrics'
import { KAFKA_CONSUMER_SESSION_TIMEOUT_MS, TeamIDWithConfig } from '../session-recordings-consumer'
import { HeatmapEvent } from '../types'
import { readTokenFromHeaders } from '../utils'

const KAFKA_CONSUMER_GROUP_ID = 'replay-heatmaps-ingestion'

function isPositiveNumber(candidate: unknown): candidate is number {
    return typeof candidate === 'number' && candidate >= 0
}

export const parseKafkaMessage = async (
    message: Message,
    getTeamFn: (s: string) => Promise<TeamIDWithConfig | null>
): Promise<HeatmapEvent[] | void> => {
    const dropMessage = (reason: string, extra?: Record<string, any>) => {
        eventDroppedCounter
            .labels({
                event_type: 'session_recordings_heatmap_ingestion',
                drop_cause: reason,
            })
            .inc()

        status.warn('⚠️', 'invalid_message', {
            reason,
            partition: message.partition,
            offset: message.offset,
            ...(extra || {}),
        })
    }

    if (!message.value || !message.timestamp) {
        // Typing says this can happen but in practice it shouldn't
        return dropMessage('message_value_or_timestamp_is_empty')
    }

    const headerResult = await readTokenFromHeaders(message.headers, getTeamFn)
    const token: string | undefined = headerResult.token
    const teamIdWithConfig: null | TeamIDWithConfig = headerResult.teamIdWithConfig

    if (!token) {
        return dropMessage('no_token_in_header')
    }

    // NB `==` so we're comparing undefined and null
    // if token was in the headers but, we could not load team config
    // then, we can return early
    if (teamIdWithConfig == null || teamIdWithConfig.teamId == null) {
        return dropMessage('header_token_present_team_missing_or_disabled', {
            token: token,
        })
    }

    let messagePayload: RawEventMessage
    let event: PipelineEvent

    try {
        messagePayload = JSON.parse(message.value.toString())
        event = JSON.parse(messagePayload.data)
    } catch (error) {
        return dropMessage('invalid_json', { error })
    }

    // TODO are we receiving some scroll values too ?
    const { $viewport_height, $viewport_width, $session_id, $heatmap_data, distinct_id } = event.properties || {}
    const teamId = teamIdWithConfig.teamId

    // NOTE: This is simple validation - ideally we should do proper schema based validation
    if (event.event !== '$heatmap') {
        return dropMessage('received_non_heatmap_message')
    }

    if (!isPositiveNumber($viewport_height) || !isPositiveNumber($viewport_width) || !$session_id) {
        return dropMessage('received_invalid_heatmap_message')
    }

    const scale_factor = 16

    let heatmapEvents: HeatmapEvent[] = []

    try {
        Object.entries($heatmap_data).forEach(([url, items]) => {
            if (Array.isArray(items)) {
                heatmapEvents = heatmapEvents.concat(
                    (items as any[]).map(
                        (hme: { x: number; y: number; target_fixed: boolean; type: string }): HeatmapEvent => ({
                            type: hme.type,
                            x: Math.ceil(hme.x / scale_factor),
                            y: Math.ceil(hme.y / scale_factor),
                            pointer_target_fixed: hme.target_fixed,
                            viewport_height: Math.ceil($viewport_height / scale_factor),
                            viewport_width: Math.ceil($viewport_width / scale_factor),
                            current_url: url,
                            session_id: $session_id,
                            scale_factor,
                            timestamp: castTimestampOrNow(
                                DateTime.fromMillis(message.timestamp ?? Date.now()),
                                TimestampFormat.ClickHouse
                            ),
                            team_id: teamId,
                            distinct_id: distinct_id,
                        })
                    )
                )
            }
        })
    } catch (e) {
        status.error('🔥', `heatmap_ingester_consumer - failed to parse heatmap data: ${e}`)
    }

    return heatmapEvents
}

/*
 * Ben and Paul are experimenting with ingestion for Heatmaps 3000
 * For several reasons we will emit a new autocaptured $heatmap event
 * And ingest that here
 *
 * Why here?
 *
 * For both familiarity and ownership reasons we're experimenting in blobby ingestion
 * rather than event ingestion
 *
 * Ultimately, to avoid confusing the future traveller, this should move to
 * either its own ingestion consumer or the event consumer
 */
export class HeatmapEventIngester {
    batchConsumer?: BatchConsumer
    private readonly config: PluginsServerConfig
    private teamsRefresher: BackgroundRefresher<Record<string, TeamIDWithConfig>>
    private sharedClusterProducerWrapper: KafkaProducerWrapper | undefined = undefined

    // TODO these are the hooks we'd use if we needed to add overflow in future
    consumerGroupId: string = KAFKA_CONSUMER_GROUP_ID
    topic: string = KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS

    constructor(private globalServerConfig: PluginsServerConfig, private postgres: PostgresRouter) {
        this.config = sessionRecordingConsumerConfig(globalServerConfig)

        this.teamsRefresher = new BackgroundRefresher(async () => {
            try {
                status.info('🔁', 'heatmap_ingester_consumer - refreshing teams in the background')
                return await fetchTeamTokensWithRecordings(this.postgres, false)
            } catch (e) {
                status.error('🔥', 'heatmap_ingester_consumer - failed to refresh teams in the background', e)
                captureException(e)
                throw e
            }
        })
    }

    private async consume(message: HeatmapEvent) {
        const producer = this.sharedClusterProducerWrapper?.producer
        if (!producer) {
            return // 🤷surely not
        }
        return produce({
            producer: producer,
            topic: KAFKA_CLICKHOUSE_HEATMAP_EVENTS,
            value: Buffer.from(JSON.stringify(message)),
            key: message.session_id,
            waitForAck: true,
        })
    }

    /**
     * take only `$heatmap` events
     * they will have an x and y as well as a width and height
     * we want to limit the cardinality of the data and will use a resolution of 16px squares
     * so each x and y is reduced to the top left of one of the 16px squares
     * e.g. an x,y of 8,8 is reduced to 0,0 because it's in the first 16px square
     * and an x,y of 44,206 is reduced to 2, 12
     * once we have reduced the resolution
     * we write the event onwards to land in ClickHouse
     */
    public async handleEachBatch(messages: Message[], heartbeat: () => void): Promise<void> {
        status.info('🔁', `heatmap_ingester_consumer - handling batch`, {
            size: messages.length,
        })

        let parsedMessages: HeatmapEvent[] = []

        for (const m of messages) {
            const parsedToIncoming = await parseKafkaMessage(m, (token) =>
                this.teamsRefresher.get().then((teams) => ({
                    teamId: teams[token]?.teamId || null,
                    // lazily reusing the same contract here even though it doesn't make sense
                    consoleLogIngestionEnabled: false,
                }))
            )
            if (parsedToIncoming) {
                parsedMessages = parsedMessages.concat(parsedToIncoming)
            }
        }

        const pendingProduceRequests = []
        for (const message of parsedMessages) {
            pendingProduceRequests.push(this.consume(message))
        }

        heartbeat()

        // just copied from replay events ingester below here - yuck

        // On each loop, we flush the producer to ensure that all messages
        // are sent to Kafka.
        try {
            await this.sharedClusterProducerWrapper?.flush()
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
                status.error('⚠️', '[heatmap_ingester_consumer] main_loop_error', { error })

                if (error?.isRetriable) {
                    // We assume if the error is retryable, then we
                    // are probably in a state where e.g. Kafka is down
                    // temporarily, and we would rather simply throw and
                    // have the process restarted.
                    throw error
                }
            }
        }
    }

    async start(): Promise<void> {
        status.info('🔁', 'heatmap_ingester_consumer - starting heatmap events consumer', {
            librdKafkaVersion: librdkafkaVersion,
            kafkaCapabilities: features,
        })

        const replayClusterConnectionConfig = createRdConnectionConfigFromEnvVars(this.config)
        const groupId = this.consumerGroupId
        const topic = this.topic
        this.batchConsumer = await startBatchConsumer({
            connectionConfig: replayClusterConnectionConfig,
            groupId,
            topic,
            autoCommit: true, // each event is an island
            sessionTimeout: KAFKA_CONSUMER_SESSION_TIMEOUT_MS,
            maxPollIntervalMs: this.config.KAFKA_CONSUMPTION_MAX_POLL_INTERVAL_MS,
            // the largest size of a message that can be fetched by the consumer.
            // the largest size our MSK cluster allows is 20MB
            // we only use 9 or 10MB but there's no reason to limit this 🤷️
            consumerMaxBytes: this.config.KAFKA_CONSUMPTION_MAX_BYTES,
            consumerMaxBytesPerPartition: this.config.KAFKA_CONSUMPTION_MAX_BYTES_PER_PARTITION,
            // our messages are very big, so we don't want to buffer too many
            queuedMinMessages: this.config.SESSION_RECORDING_KAFKA_QUEUE_SIZE,
            consumerMaxWaitMs: this.config.KAFKA_CONSUMPTION_MAX_WAIT_MS,
            consumerErrorBackoffMs: this.config.KAFKA_CONSUMPTION_ERROR_BACKOFF_MS,
            fetchBatchSize: this.config.SESSION_RECORDING_KAFKA_BATCH_SIZE,
            batchingTimeoutMs: this.config.KAFKA_CONSUMPTION_BATCHING_TIMEOUT_MS,
            topicCreationTimeoutMs: this.config.KAFKA_TOPIC_CREATION_TIMEOUT_MS,
            eachBatch: async (messages, { heartbeat }) => {
                return this.handleEachBatch(messages, heartbeat)
            },
            callEachBatchWhenEmpty: false,
            debug: this.config.SESSION_RECORDING_KAFKA_DEBUG,
        })

        const globalConnectionConfig = createRdConnectionConfigFromEnvVars(this.globalServerConfig)
        const globalProducerConfig = createRdProducerConfigFromEnvVars(this.globalServerConfig)

        this.sharedClusterProducerWrapper = new KafkaProducerWrapper(
            await createKafkaProducer(globalConnectionConfig, globalProducerConfig)
        )
        this.sharedClusterProducerWrapper.producer.connect()
    }

    async stop(): Promise<PromiseSettledResult<any>[]> {
        status.info('🔁', 'heatmap_ingester_consumer - stopping heatmap events consumer')

        return Promise.allSettled([
            this.sharedClusterProducerWrapper ? this.sharedClusterProducerWrapper.disconnect() : Promise.resolve(),
        ])
    }

    public isHealthy() {
        return this.batchConsumer?.isHealthy()
    }
}
