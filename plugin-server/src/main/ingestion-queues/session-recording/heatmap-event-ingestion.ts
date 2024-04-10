import { captureException } from '@sentry/node'
import { DateTime } from 'luxon'
import { features, librdkafkaVersion, Message } from 'node-rdkafka'

import { sessionRecordingConsumerConfig } from '../../../config/config'
import { KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS } from '../../../config/kafka-topics'
import { BatchConsumer, startBatchConsumer } from '../../../kafka/batch-consumer'
import { createRdConnectionConfigFromEnvVars } from '../../../kafka/config'
import { PipelineEvent, PluginsServerConfig, RawEventMessage, TimestampFormat } from '../../../types'
import { BackgroundRefresher } from '../../../utils/background-refresher'
import { PostgresRouter } from '../../../utils/db/postgres'
import { status } from '../../../utils/status'
import { castTimestampOrNow } from '../../../utils/utils'
import { fetchTeamTokensWithRecordings } from '../../../worker/ingestion/team-manager'
import { eventDroppedCounter } from '../metrics'
import {
    KAFKA_CONSUMER_GROUP_ID,
    KAFKA_CONSUMER_SESSION_TIMEOUT_MS,
    TeamIDWithConfig,
} from './session-recordings-consumer'
import { HeatmapEvent, IncomingHeatmapEventMessage } from './types'
import { readTokenFromHeaders } from './utils'

function isPositiveNumber(x: unknown): x is number {
    return typeof x === 'number' && x > 0
}

export const parseKafkaMessage = async (
    message: Message,
    getTeamFn: (s: string) => Promise<TeamIDWithConfig | null>
): Promise<IncomingHeatmapEventMessage | void> => {
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
    const { screen_height, screen_width, $session_id, x, y } = event.properties || {}

    // NOTE: This is simple validation - ideally we should do proper schema based validation
    if (
        event.event !== '$heatmap' &&
        isPositiveNumber(screen_height) &&
        isPositiveNumber(screen_width) &&
        isPositiveNumber(x) &&
        isPositiveNumber(y) &&
        !!$session_id
    ) {
        return dropMessage('received_non_heatmap_message')
    }

    return {
        metadata: {
            partition: message.partition,
            topic: message.topic,
            timestamp: message.timestamp,
        },
        team_id: teamIdWithConfig?.teamId,
        screen_height,
        screen_width,
        session_id: $session_id,
        x,
        y,
    }
}

function parsedHeatmapMessages(incomingMessages: IncomingHeatmapEventMessage[]): HeatmapEvent[] {
    return incomingMessages.map((rhe) => ({
        ...rhe,
        quadrant_x: Math.ceil(rhe.x / 16),
        quadrant_y: Math.ceil(rhe.y / 16),
        resolution: 16,
        timestamp: castTimestampOrNow(DateTime.fromMillis(rhe.metadata.timestamp), TimestampFormat.ClickHouse),
    }))
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
    config: PluginsServerConfig
    teamsRefresher: BackgroundRefresher<Record<string, TeamIDWithConfig>>

    // TODO these are the hooks we'd use if we needed to add overflow in future
    consumerGroupId: string = KAFKA_CONSUMER_GROUP_ID
    topic: string = KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS

    constructor(private globalServerConfig: PluginsServerConfig, private postgres: PostgresRouter) {
        this.config = sessionRecordingConsumerConfig(globalServerConfig)

        this.teamsRefresher = new BackgroundRefresher(async () => {
            try {
                status.info('🔁', 'heatmap_ingester_consumer - refreshing teams in the background')
                return await fetchTeamTokensWithRecordings(this.postgres)
            } catch (e) {
                status.error('🔥', 'heatmap_ingester_consumer - failed to refresh teams in the background', e)
                captureException(e)
                throw e
            }
        })
    }

    private async consume(_message: HeatmapEvent) {}

    public async handleEachBatch(messages: Message[], heartbeat: () => void): Promise<void> {
        status.info('🔁', `heatmap_ingester_consumer - handling batch`, {
            size: messages.length,
        })

        // take only `$heatmap` events
        // they will have an x and y as well as a width and height
        // we want to limit the cardinality of the data and will use a resolution of 16px squares
        // so each x and y is reduced to the top left of one of the 16px squares
        // e.g. an x,y of 8,8 is reduced to 0,0 because it's in the first 16px square
        // and an x,y of 44,206 is reduced to 2, 12
        // once we have reduced the resolution
        // we write the event onwards to land in ClickHouse

        const incomingMessages: IncomingHeatmapEventMessage[] = []

        for (const m of messages) {
            const parsedToIncoming = await parseKafkaMessage(m, (token) =>
                this.teamsRefresher.get().then((teams) => ({
                    teamId: teams[token]?.teamId || null,
                    // lazily reusing value here even though it doesn't make sense
                    consoleLogIngestionEnabled: false,
                }))
            )
            if (parsedToIncoming) {
                incomingMessages.push(parsedToIncoming)
            }
        }

        status.info('🔁', `heatmap_ingester_consumer - filtered batch`, {
            size: messages.length,
            filteredSize: incomingMessages.length,
        })

        const parsedMessages: HeatmapEvent[] = parsedHeatmapMessages(incomingMessages)

        for (const message of parsedMessages) {
            await this.consume(message)
            heartbeat()
        }
    }

    async start(): Promise<void> {
        status.info('🔁', 'heatmap_ingester_consumer - starting heatmap events consumer', {
            librdKafkaVersion: librdkafkaVersion,
            kafkaCapabilities: features,
        })

        const replayClusterConnectionConfig = createRdConnectionConfigFromEnvVars(this.config)
        this.batchConsumer = await startBatchConsumer({
            connectionConfig: replayClusterConnectionConfig,
            groupId: this.consumerGroupId,
            topic: this.topic,
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
            callEachBatchWhenEmpty: true, // Useful as we will still want to account for flushing sessions
            debug: this.config.SESSION_RECORDING_KAFKA_DEBUG,
        })
    }

    async stop(): Promise<PromiseSettledResult<any>[]> {
        return Promise.resolve([])
    }

    public isHealthy() {
        return this.batchConsumer?.isHealthy()
    }
}
