import { features, librdkafkaVersion, Message } from 'node-rdkafka'

import { sessionRecordingConsumerConfig } from '../../../config/config'
import { KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS } from '../../../config/kafka-topics'
import { BatchConsumer, startBatchConsumer } from '../../../kafka/batch-consumer'
import { createRdConnectionConfigFromEnvVars } from '../../../kafka/config'
import { PluginsServerConfig } from '../../../types'
import { status } from '../../../utils/status'
import { KAFKA_CONSUMER_GROUP_ID, KAFKA_CONSUMER_SESSION_TIMEOUT_MS } from './session-recordings-consumer'
import { HeatmapEvent, IncomingHeatmapEventMessage } from './types'

function parsedHeatmapMessages(_incomingMessages: IncomingHeatmapEventMessage[]): HeatmapEvent[] {
    return []
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

    // TODO these are the hooks we'd use if we needed to add overflow in future
    consumerGroupId: string = KAFKA_CONSUMER_GROUP_ID
    topic: string = KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS

    constructor(private globalServerConfig: PluginsServerConfig) {
        this.config = sessionRecordingConsumerConfig(globalServerConfig)
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
