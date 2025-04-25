import { BatchConsumer, startBatchConsumer } from '../../../kafka/batch-consumer'
import { createRdConnectionConfigFromEnvVars } from '../../../kafka/config'
import { PluginsServerConfig } from '../../../types'
import { addSentryBreadcrumbsEventListeners } from '../kafka-metrics'
import { KAFKA_CONSUMER_SESSION_TIMEOUT_MS } from './constants'
import { EachBatchHandler } from './types'

export interface BatchConsumerFactory {
    createBatchConsumer(groupId: string, topic: string, eachBatch: EachBatchHandler): Promise<BatchConsumer>
}

export class DefaultBatchConsumerFactory implements BatchConsumerFactory {
    private readonly kafkaConfig: PluginsServerConfig

    constructor(private readonly serverConfig: PluginsServerConfig) {
        // TRICKY: We re-use the kafka helpers which assume KAFKA_HOSTS hence we overwrite it if set
        this.kafkaConfig = {
            ...serverConfig,
            KAFKA_HOSTS: serverConfig.SESSION_RECORDING_KAFKA_HOSTS || serverConfig.KAFKA_HOSTS,
            KAFKA_SECURITY_PROTOCOL:
                serverConfig.SESSION_RECORDING_KAFKA_SECURITY_PROTOCOL || serverConfig.KAFKA_SECURITY_PROTOCOL,
        }
    }

    public async createBatchConsumer(
        groupId: string,
        topic: string,
        eachBatch: EachBatchHandler
    ): Promise<BatchConsumer> {
        const connectionConfig = createRdConnectionConfigFromEnvVars(this.kafkaConfig, 'consumer')
        // Create a node-rdkafka consumer that fetches batches of messages, runs
        // eachBatch with context, then commits offsets for the batch.
        // the batch consumer reads from the session replay kafka cluster
        const consumer = await startBatchConsumer({
            connectionConfig,
            groupId,
            topic,
            eachBatch,
            callEachBatchWhenEmpty: true, // Required, as we want to flush session batches periodically
            autoCommit: true,
            autoOffsetStore: false,
            sessionTimeout: KAFKA_CONSUMER_SESSION_TIMEOUT_MS,
            maxPollIntervalMs: this.serverConfig.KAFKA_CONSUMPTION_MAX_POLL_INTERVAL_MS,
            // the largest size of a message that can be fetched by the consumer.
            // the largest size our MSK cluster allows is 20MB
            // we only use 9 or 10MB but there's no reason to limit this 🤷️
            consumerMaxBytes: this.serverConfig.KAFKA_CONSUMPTION_MAX_BYTES,
            consumerMaxBytesPerPartition: this.serverConfig.KAFKA_CONSUMPTION_MAX_BYTES_PER_PARTITION,
            fetchMinBytes: this.serverConfig.SESSION_RECORDING_KAFKA_FETCH_MIN_BYTES,
            // our messages are very big, so we don't want to queue too many
            queuedMinMessages: this.serverConfig.SESSION_RECORDING_KAFKA_QUEUE_SIZE,
            // we'll anyway never queue more than the value set here
            // since we have large messages we'll need this to be a reasonable multiple
            // of the likely message size times the fetchBatchSize
            // or we'll always hit the batch timeout
            queuedMaxMessagesKBytes: this.serverConfig.SESSION_RECORDING_KAFKA_QUEUE_SIZE_KB,
            fetchBatchSize: this.serverConfig.SESSION_RECORDING_KAFKA_BATCH_SIZE,
            consumerMaxWaitMs: this.serverConfig.KAFKA_CONSUMPTION_MAX_WAIT_MS,
            consumerErrorBackoffMs: this.serverConfig.KAFKA_CONSUMPTION_ERROR_BACKOFF_MS,
            batchingTimeoutMs: this.serverConfig.KAFKA_CONSUMPTION_BATCHING_TIMEOUT_MS,
            topicMetadataRefreshInterval: this.serverConfig.KAFKA_TOPIC_METADATA_REFRESH_INTERVAL_MS,
            debug: this.serverConfig.SESSION_RECORDING_KAFKA_DEBUG,
            kafkaStatisticIntervalMs:
                this.serverConfig.SESSION_RECORDING_KAFKA_CONSUMPTION_STATISTICS_EVENT_INTERVAL_MS,
            maxHealthHeartbeatIntervalMs: KAFKA_CONSUMER_SESSION_TIMEOUT_MS * 2,
        })

        addSentryBreadcrumbsEventListeners(consumer.consumer)
        return consumer
    }
}
