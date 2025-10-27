import {
    Assignment,
    CODES,
    ClientMetrics,
    ConsumerGlobalConfig,
    LibrdKafkaError,
    Message,
    MessageHeader,
    Metadata,
    PartitionMetadata,
    KafkaConsumer as RdKafkaConsumer,
    TopicPartitionOffset,
    WatermarkOffsets,
} from 'node-rdkafka'
import { hostname } from 'os'
import { Counter, Gauge, Histogram } from 'prom-client'

import {
    EventHeaders,
    HealthCheckResult,
    HealthCheckResultDegraded,
    HealthCheckResultError,
    HealthCheckResultOk,
    LogLevel,
} from '~/types'
import { isTestEnv } from '~/utils/env-utils'
import { parseJSON } from '~/utils/json-parse'

import { defaultConfig } from '../config/config'
import { kafkaConsumerAssignment, kafkaHeaderStatusCounter } from '../main/ingestion-queues/metrics'
import { logger } from '../utils/logger'
import { captureException } from '../utils/posthog'
import { retryIfRetriable } from '../utils/retries'
import { promisifyCallback } from '../utils/utils'
import { ensureTopicExists } from './admin'
import { getKafkaConfigFromEnv } from './config'
import { parseBrokerStatistics, trackBrokerMetrics } from './kafka-client-metrics'

const DEFAULT_BATCH_TIMEOUT_MS = 500
const SLOW_BATCH_PROCESSING_LOG_THRESHOLD_MS = 10000
const MAX_HEALTH_HEARTBEAT_INTERVAL_MS = 60_000
const STATISTICS_INTERVAL_MS = 5000 // Emit internal metrics every 5 seconds

const consumedBatchDuration = new Histogram({
    name: 'consumed_batch_duration_ms',
    help: 'Main loop consumer batch processing duration in ms',
    labelNames: ['topic', 'groupId'],
})

const consumedBatchBackgroundDuration = new Histogram({
    name: 'consumed_batch_background_duration_ms',
    help: 'Background task processing duration in ms',
    labelNames: ['topic', 'groupId'],
})

const consumedBatchBackpressureDuration = new Histogram({
    name: 'consumed_batch_backpressure_duration_ms',
    help: 'Time spent waiting for background work to finish due to backpressure',
    labelNames: ['topic', 'groupId'],
})

const gaugeBatchUtilization = new Gauge({
    name: 'consumer_batch_utilization',
    help: 'Indicates how big batches are we are processing compared to the max batch size. Useful as a scaling metric',
    labelNames: ['groupId'],
})

const histogramKafkaBatchSize = new Histogram({
    name: 'consumer_batch_size',
    help: 'The size of the batches we are receiving from Kafka',
    buckets: [0, 50, 100, 250, 500, 750, 1000, 1500, 2000, 3000, Infinity],
})

const histogramKafkaBatchSizeKb = new Histogram({
    name: 'consumer_batch_size_kb',
    help: 'The size in kb of the batches we are receiving from Kafka',
    buckets: [0, 128, 512, 1024, 5120, 10240, 20480, 51200, 102400, 204800, Infinity],
})

const histogramKafkaConsumeInterval = new Histogram({
    name: 'kafka_consume_interval_ms',
    help: 'Time elapsed between Kafka consume calls',
    labelNames: ['topic', 'groupId'],
    buckets: [0, 20, 100, 200, 500, 1000, 2500, 5000, 10000, 20000, 30000, 60000, Infinity],
})

const gaugeOldestBackgroundTaskAge = new Gauge({
    name: 'consumer_oldest_background_task_age_ms',
    help: 'Age of the oldest background task in queue - if this grows unbounded, pod is stuck',
    labelNames: ['pod', 'groupId'],
})

const gaugeTimeSinceLastProgress = new Gauge({
    name: 'consumer_time_since_last_progress_ms',
    help: 'Time since any background task completed - shows if pod is making any progress',
    labelNames: ['pod', 'groupId'],
})

const counterBackgroundTaskNotFound = new Counter({
    name: 'consumer_background_task_not_found_total',
    help: 'Background task attempted cleanup but was not found in array - indicates serious system integrity issue',
    labelNames: ['pod', 'groupId'],
})

export const findOffsetsToCommit = (messages: TopicPartitionOffset[]): TopicPartitionOffset[] => {
    // We only need to commit the highest offset for a batch of messages
    const messagesByTopicPartition = messages.reduce(
        (acc, message) => {
            if (!acc[message.topic]) {
                acc[message.topic] = {}
            }

            if (!acc[message.topic][message.partition]) {
                acc[message.topic][message.partition] = []
            }

            acc[message.topic][message.partition].push(message)

            return acc
        },
        {} as { [topic: string]: { [partition: number]: TopicPartitionOffset[] } }
    )

    // Then we find the highest offset for each topic partition
    const highestOffsets = Object.entries(messagesByTopicPartition).flatMap(([topic, partitions]) => {
        return Object.entries(partitions).map(([partition, messages]) => {
            const highestOffset = Math.max(...messages.map((message) => message.offset))

            return {
                topic,
                partition: parseInt(partition),
                // When committing to Kafka you commit the offset of the next message you want to consume
                offset: highestOffset + 1,
            }
        })
    })

    return highestOffsets
}

export type KafkaConsumerConfig = {
    groupId: string
    topic: string
    batchTimeoutMs?: number
    callEachBatchWhenEmpty?: boolean
    autoOffsetStore?: boolean
    autoCommit?: boolean
    waitForBackgroundTasksOnRebalance?: boolean
}

export type RdKafkaConsumerConfig = Omit<
    ConsumerGlobalConfig,
    'group.id' | 'enable.auto.offset.store' | 'enable.auto.commit'
>

type RebalanceCallback = boolean | ((err: LibrdKafkaError, assignments: Assignment[]) => void)

interface RebalanceCoordination {
    isRebalancing: boolean
    rebalanceTimeoutMs: number
    rebalanceStartTime: number
}

export class KafkaConsumer {
    private isStopping = false
    private lastHeartbeatTime = 0
    private rdKafkaConsumer: RdKafkaConsumer
    private consumerConfig: ConsumerGlobalConfig
    private fetchBatchSize: number
    private maxHealthHeartbeatIntervalMs: number
    private maxBackgroundTasks: number
    private consumerLoop: Promise<void> | undefined
    private backgroundTask: { promise: Promise<void>; createdAt: number }[]
    private podName: string
    private lastBackgroundTaskCompletionTime: number
    private consumerId: string
    // New health monitoring state
    private consumerLoopStallThresholdMs: number
    private lastConsumerLoopTime = 0
    private consumerState: string | undefined
    private lastStatsEmitTime = 0
    private rebalanceCoordination: RebalanceCoordination = {
        isRebalancing: false,
        rebalanceTimeoutMs: 20000,
        rebalanceStartTime: 0,
    }
    private consumerLogStatsLevel: LogLevel

    constructor(
        private config: KafkaConsumerConfig,
        rdKafkaConfig: RdKafkaConsumerConfig = {}
    ) {
        this.backgroundTask = []
        this.podName = process.env.HOSTNAME || hostname()
        this.lastBackgroundTaskCompletionTime = Date.now()
        // Generate unique consumer ID: pod + group + timestamp + random number (need timestamp/random number because multiple consumers per pod)
        this.consumerId = `${this.podName}-${this.config.groupId}-${Date.now()}-${Math.random().toString(36).substring(2, 8)}`

        this.config.autoCommit ??= true
        this.config.autoOffsetStore ??= true
        this.config.callEachBatchWhenEmpty ??= false
        this.config.waitForBackgroundTasksOnRebalance = defaultConfig.CONSUMER_WAIT_FOR_BACKGROUND_TASKS_ON_REBALANCE
        this.maxBackgroundTasks = defaultConfig.CONSUMER_MAX_BACKGROUND_TASKS
        this.fetchBatchSize = defaultConfig.CONSUMER_BATCH_SIZE
        this.maxHealthHeartbeatIntervalMs =
            defaultConfig.CONSUMER_MAX_HEARTBEAT_INTERVAL_MS || MAX_HEALTH_HEARTBEAT_INTERVAL_MS
        this.consumerLoopStallThresholdMs = defaultConfig.CONSUMER_LOOP_STALL_THRESHOLD_MS
        this.consumerLogStatsLevel = defaultConfig.CONSUMER_LOG_STATS_LEVEL

        const rebalancecb: RebalanceCallback = this.config.waitForBackgroundTasksOnRebalance
            ? this.rebalanceCallback.bind(this)
            : true

        this.consumerConfig = {
            'client.id': hostname(),
            'security.protocol': 'plaintext',
            'metadata.broker.list': 'kafka:9092', // Overridden with KAFKA_CONSUMER_METADATA_BROKER_LIST
            log_level: 4, // WARN as the default
            'group.id': this.config.groupId,
            'session.timeout.ms': 30_000,
            'max.poll.interval.ms': 300_000,
            'max.partition.fetch.bytes': 1_048_576,
            'fetch.error.backoff.ms': 100,
            'fetch.message.max.bytes': 10_485_760,
            'fetch.wait.max.ms': 50,
            'queued.min.messages': 100000,
            'queued.max.messages.kbytes': 102400, // 1048576 is the default, we go smaller to reduce mem usage.
            'client.rack': defaultConfig.KAFKA_CLIENT_RACK, // Helps with cross-AZ traffic awareness and is not unique to the consumer
            'metadata.max.age.ms': 30000, // Refresh metadata every 30s - Relevant for leader loss (MSK Security Patches)
            'socket.timeout.ms': 30000,
            // Only enable statistics when using loop-based health check
            ...(defaultConfig.CONSUMER_LOOP_BASED_HEALTH_CHECK
                ? { 'statistics.interval.ms': STATISTICS_INTERVAL_MS }
                : {}),
            // Custom settings and overrides - this is where most configuration overrides should be done
            ...getKafkaConfigFromEnv('CONSUMER'),
            // Finally any specifically given consumer config overrides
            ...rdKafkaConfig,
            // Below is config that we explicitly DO NOT want to be overrideable by env vars - i.e. things that would require code changes to change
            'partition.assignment.strategy': isTestEnv() ? 'roundrobin' : 'cooperative-sticky', // Roundrobin is used for testing to avoid flakiness caused by running librdkafka v2.2.0
            'enable.auto.offset.store': false, // NOTE: This is always false - we handle it using a custom function
            'enable.auto.commit': this.config.autoCommit,
            'enable.partition.eof': true,
            rebalance_cb: rebalancecb,
            offset_commit_cb: true,
        }

        this.rdKafkaConsumer = this.createConsumer()
    }

    public getConfig(): ConsumerGlobalConfig {
        return {
            ...this.consumerConfig,
        }
    }

    public heartbeat(): void {
        // Can be called externally to update the heartbeat time and keep the consumer alive
        // This is maintained for backward compatibility with the legacy health check mechanism
        this.lastHeartbeatTime = Date.now()
    }

    public isHealthy(): HealthCheckResult {
        // Use legacy heartbeat-based health check if feature flag is disabled
        if (!defaultConfig.CONSUMER_LOOP_BASED_HEALTH_CHECK) {
            // this is called as a readiness and a liveness probe
            const isWithinInterval = Date.now() - this.lastHeartbeatTime < this.maxHealthHeartbeatIntervalMs
            const isConnected = this.rdKafkaConsumer.isConnected()

            if (isConnected && isWithinInterval) {
                return new HealthCheckResultOk()
            } else {
                return new HealthCheckResultError('Consumer unhealthy', {
                    isConnected,
                    isWithinInterval,
                    lastHeartbeatTime: this.lastHeartbeatTime,
                    maxHealthHeartbeatIntervalMs: this.maxHealthHeartbeatIntervalMs,
                })
            }
        }

        // New loop-based health check implementation
        const details: Record<string, any> = {
            topic: this.config.topic,
            groupId: this.config.groupId,
            healthCheckMode: 'loop-based',
        }

        // 1. Basic connectivity check
        if (!this.rdKafkaConsumer.isConnected()) {
            return new HealthCheckResultError('Consumer not connected to Kafka broker', details)
        }

        // 2. Consumer loop liveness check (ensure loop is not stalled)
        const timeSinceLastLoop = Date.now() - this.lastConsumerLoopTime
        if (this.lastConsumerLoopTime > 0 && timeSinceLastLoop > this.consumerLoopStallThresholdMs) {
            return new HealthCheckResultError(
                `Consumer loop appears stalled (no activity for ${Math.round(timeSinceLastLoop / 1000)}s)`,
                {
                    ...details,
                    lastConsumerLoopTime: this.lastConsumerLoopTime,
                    timeSinceLastLoop,
                    threshold: this.consumerLoopStallThresholdMs,
                }
            )
        }

        // Build status message with warnings
        const warnings: string[] = []

        // 3. Check librdkafka internal state if available
        if (this.consumerState && this.consumerState !== 'up') {
            warnings.push(`Consumer state: ${this.consumerState}`)
            details.consumerState = this.consumerState
        }

        // 4. Check if statistics are being emitted (indicates librdkafka is responsive)
        if (this.lastStatsEmitTime > 0) {
            const timeSinceLastStats = Date.now() - this.lastStatsEmitTime
            // Allow for 3x the statistics interval as buffer
            if (timeSinceLastStats > STATISTICS_INTERVAL_MS * 3) {
                warnings.push(`Statistics not emitted for ${Math.round(timeSinceLastStats / 1000)}s`)
                details.lastStatsEmitTime = this.lastStatsEmitTime
                details.timeSinceLastStats = timeSinceLastStats
            }
        }

        // 5. Rebalancing is normal operation, note it but don't fail
        if (this.rebalanceCoordination.isRebalancing) {
            const duration = Date.now() - this.rebalanceCoordination.rebalanceStartTime
            warnings.push(`Rebalancing in progress (${Math.round(duration / 1000)}s)`)
            details.rebalancing = true
            details.rebalanceDuration = duration
        }

        // Add assignments info (but handle errors gracefully)
        try {
            const assignments = this.assignments()
            if (assignments.length > 0) {
                details.assignments = assignments.map((a) => ({ topic: a.topic, partition: a.partition }))
            }
        } catch (error) {
            // Consumer might be in an erroneous state during rebalancing
            details.assignmentError = error.message
        }

        // Return degraded if there are warnings, otherwise healthy
        if (warnings.length > 0) {
            return new HealthCheckResultDegraded(`Healthy with warnings: ${warnings.join(', ')}`, details)
        }

        return new HealthCheckResultOk()
    }

    public isShuttingDown(): boolean {
        return this.isStopping
    }

    public isRebalancing(): boolean {
        return this.rebalanceCoordination.isRebalancing
    }

    public assignments(): Assignment[] {
        return this.rdKafkaConsumer.isConnected() ? this.rdKafkaConsumer.assignments() : []
    }

    public offsetsStore(topicPartitionOffsets: TopicPartitionOffset[]): void {
        return this.rdKafkaConsumer.offsetsStore(topicPartitionOffsets)
    }

    public on: RdKafkaConsumer['on'] = (...args) => {
        // Delegate to the internal consumer
        return this.rdKafkaConsumer.on(...args)
    }

    public async queryWatermarkOffsets(topic: string, partition: number, timeout = 10000): Promise<[number, number]> {
        if (!this.rdKafkaConsumer.isConnected()) {
            throw new Error('Not connected')
        }

        const offsets = await promisifyCallback<WatermarkOffsets>((cb) =>
            this.rdKafkaConsumer.queryWatermarkOffsets(topic, partition, timeout, cb)
        ).catch((err) => {
            captureException(err)
            logger.error('🔥', 'Failed to query kafka watermark offsets', err)
            throw err
        })

        return [offsets.lowOffset, offsets.highOffset]
    }

    public async getPartitionsForTopic(topic: string): Promise<PartitionMetadata[]> {
        if (!this.rdKafkaConsumer.isConnected()) {
            throw new Error('Not connected')
        }

        const meta = await promisifyCallback<Metadata>((cb) => this.rdKafkaConsumer.getMetadata({ topic }, cb)).catch(
            (err) => {
                captureException(err)
                logger.error('🔥', 'Failed to get partition metadata', err)
                throw err
            }
        )

        return meta.topics.find((x) => x.name === topic)?.partitions ?? []
    }

    public rebalanceCallback(err: LibrdKafkaError, assignments: Assignment[]): void {
        logger.info('🔁', 'kafka_consumer_rebalancing', { err, assignments })

        if (err.code === CODES.ERRORS.ERR__ASSIGN_PARTITIONS) {
            // Mark rebalancing as complete when partitions are assigned
            if (this.config.waitForBackgroundTasksOnRebalance) {
                this.resetRebalanceCoordination()
            }
            assignments.forEach((tp) => {
                kafkaConsumerAssignment.set(
                    {
                        topic_name: tp.topic,
                        partition_id: tp.partition.toString(),
                        pod: this.podName,
                        group_id: this.config.groupId,
                    },
                    1
                )
            })
            if (this.rdKafkaConsumer.rebalanceProtocol() === 'COOPERATIVE') {
                this.rdKafkaConsumer.incrementalAssign(assignments)
            } else {
                this.rdKafkaConsumer.assign(assignments)
            }
        } else if (err.code === CODES.ERRORS.ERR__REVOKE_PARTITIONS) {
            // Mark rebalancing as starting when partitions are revoked
            if (this.config.waitForBackgroundTasksOnRebalance) {
                this.rebalanceCoordination.isRebalancing = true
                this.rebalanceCoordination.rebalanceStartTime = Date.now()
            }
            logger.info('🔁', 'partition_revocation_starting', {
                backgroundTaskCount: this.backgroundTask.length,
                revokedPartitions: assignments.map((tp) => ({
                    topic: tp.topic,
                    partition: tp.partition,
                })),
            })

            // Handle background task coordination asynchronously
            if (this.config.waitForBackgroundTasksOnRebalance && this.backgroundTask.length > 0) {
                // Don't block the rebalance callback, but coordinate in the background
                Promise.all(this.backgroundTask.map((t) => t.promise))
                    .then(() => {
                        logger.info('🔁', 'background_tasks_completed_before_partition_revocation')
                        if (this.rdKafkaConsumer.rebalanceProtocol() === 'COOPERATIVE') {
                            this.rdKafkaConsumer.incrementalUnassign(assignments)
                        } else {
                            this.rdKafkaConsumer.unassign()
                        }
                        this.updateMetricsAfterRevocation(assignments)
                        if (this.assignments().length === 0) {
                            this.resetRebalanceCoordination()
                        }
                    })
                    .catch((error) => {
                        logger.error('🔁', 'background_task_error_during_revocation', { error })
                        // Still proceed with revocation even if background tasks fail
                        if (this.rdKafkaConsumer.rebalanceProtocol() === 'COOPERATIVE') {
                            this.rdKafkaConsumer.incrementalUnassign(assignments)
                        } else {
                            this.rdKafkaConsumer.unassign()
                        }
                        this.updateMetricsAfterRevocation(assignments)
                        if (this.assignments().length === 0) {
                            this.resetRebalanceCoordination()
                        }
                    })
            } else {
                // No background tasks or feature disabled, proceed immediately
                if (this.rdKafkaConsumer.rebalanceProtocol() === 'COOPERATIVE') {
                    this.rdKafkaConsumer.incrementalUnassign(assignments)
                } else {
                    this.rdKafkaConsumer.unassign()
                }
                this.updateMetricsAfterRevocation(assignments)
            }
        } else {
            // Ignore exceptions if we are not connected
            if (this.rdKafkaConsumer.isConnected()) {
                logger.error('🔥', 'kafka_consumer_rebalancing_error', { err })
                captureException(err)
            } else {
                logger.warn('🔥', 'kafka_consumer_rebalancing_error_while_not_connected', { err })
            }
        }
    }

    private updateMetricsAfterRevocation(assignments: Assignment[]): void {
        assignments.forEach((tp) => {
            kafkaConsumerAssignment.set(
                {
                    topic_name: tp.topic,
                    partition_id: tp.partition.toString(),
                    pod: this.podName,
                    group_id: this.config.groupId,
                },
                0
            )
        })
    }

    private createConsumer(): RdKafkaConsumer {
        const consumer = new RdKafkaConsumer(this.consumerConfig, {
            // Default settings
            'auto.offset.reset': 'earliest',
        })

        consumer.on('event.log', (log) => {
            logger.info('📝', 'librdkafka log', { log: log })
        })

        consumer.on('event.error', (error: LibrdKafkaError) => {
            logger.error('📝 librdkafka error', {
                message: error.message,
                code: error.code,
                errno: error.errno,
                origin: 'event.error',
                stack: error.stack,
            })
        })

        consumer.on('event.stats', (stats: any) => {
            // Parse the statistics JSON
            try {
                const parsedStats = parseJSON(stats.message)

                // Update internal health monitoring state
                this.lastStatsEmitTime = Date.now()
                // cgrp field only appears when consumer is part of a group
                this.consumerState = parsedStats.cgrp?.state || 'no-group'

                const brokerStats = parseBrokerStatistics(parsedStats)

                trackBrokerMetrics(brokerStats, this.config.groupId, this.consumerId)

                // Log key metrics for observability - only include cgrp fields if present
                const logData: any = {
                    rx_msgs: parsedStats.rxmsgs, // Total messages received
                    rx_bytes: parsedStats.rx_bytes || parsedStats.rxbytes, // Total bytes received
                    topics: Object.keys(parsedStats.topics || {}),
                    broker_count: brokerStats.size,
                    brokers: Array.from(brokerStats.entries()).map(([name, stats]) => ({
                        ...stats,
                        name,
                    })),
                }

                // Only add consumer group fields if cgrp exists
                if (parsedStats.cgrp) {
                    logData.consumer_group_state = parsedStats.cgrp.state
                    logData.rebalance_state = parsedStats.cgrp.join_state
                    logData.rebalance_age = parsedStats.cgrp.rebalance_age
                    logData.rebalance_cnt = parsedStats.cgrp.rebalance_cnt
                    logData.assignment_size = parsedStats.cgrp.assignment_size
                }

                logger[this.consumerLogStatsLevel]('📊', 'Kafka consumer statistics', logData)
            } catch (error) {
                logger.error('📊', 'Failed to parse consumer statistics', {
                    error: error instanceof Error ? error.message : String(error),
                    errorStack: error instanceof Error ? error.stack : undefined,
                })
            }
        })

        consumer.on('subscribed', (topics) => {
            logger.info('📝', 'librdkafka consumer subscribed', { topics, config: this.consumerConfig })
        })

        consumer.on('connection.failure', (error: LibrdKafkaError, metrics: ClientMetrics) => {
            logger.error('📝', 'librdkafka connection failure', { error, metrics, config: this.consumerConfig })
        })

        consumer.on('offset.commit', (error: LibrdKafkaError, topicPartitionOffsets: TopicPartitionOffset[]) => {
            if (error) {
                logger.warn('📝', 'librdkafka_offet_commit_error', { error, topicPartitionOffsets })
            } else {
                logger.debug('📝', 'librdkafka_offset_commit', { topicPartitionOffsets })
            }
        })

        return consumer
    }

    private storeOffsetsForMessages = (topicPartitionOffsetsToCommit: TopicPartitionOffset[]): void => {
        if (topicPartitionOffsetsToCommit.length > 0) {
            logger.debug('📝', 'Storing offsets', { topicPartitionOffsetsToCommit })
            try {
                this.rdKafkaConsumer.offsetsStore(topicPartitionOffsetsToCommit)
            } catch (e) {
                // NOTE: We don't throw here - this can happen if we were re-assigned partitions
                // and the offsets are no longer valid whilst processing a batch
                logger.error('📝', 'Failed to store offsets', {
                    error: String(e),
                    assignedPartitions: this.assignments(),
                    topicPartitionOffsetsToCommit,
                })
                captureException(e)
            }
        }
    }

    public async connect(
        eachBatch: (messages: Message[]) => Promise<{ backgroundTask?: Promise<any> } | void>
    ): Promise<void> {
        const { topic, groupId, callEachBatchWhenEmpty = false } = this.config

        try {
            await promisifyCallback<Metadata>((cb) => this.rdKafkaConsumer.connect({}, cb))
            logger.info('📝', 'librdkafka consumer connected')
        } catch (error) {
            logger.error('⚠️', 'connect_error', { error: error })
            throw error
        }

        this.heartbeat() // Setup the heartbeat so we are healthy since connection is established

        // Initialize health monitoring state for new loop-based check
        this.lastConsumerLoopTime = Date.now()

        if (defaultConfig.CONSUMER_AUTO_CREATE_TOPICS) {
            // For hobby deploys we want to auto-create, but on cloud we don't
            await ensureTopicExists(this.consumerConfig, this.config.topic)
        }

        // The consumer has an internal pre-fetching queue that sequentially pools
        // each partition, with the consumerMaxWaitMs timeout. We want to read big
        // batches from this queue, but guarantee we are still running (with smaller
        // batches) if the queue is not full enough. batchingTimeoutMs is that
        // timeout, to return messages even if fetchBatchSize is not reached.
        this.rdKafkaConsumer.setDefaultConsumeTimeout(this.config.batchTimeoutMs || DEFAULT_BATCH_TIMEOUT_MS)
        this.rdKafkaConsumer.subscribe([this.config.topic])

        const startConsuming = async (): Promise<void> => {
            let lastConsumeTime = 0
            try {
                while (!this.isStopping) {
                    // Track that the consumer loop is alive
                    this.lastConsumerLoopTime = Date.now()
                    logger.debug('🔁', 'main_loop_consuming')

                    // If we're rebalancing and feature flag is enabled, skip consuming to avoid processing messages
                    // during rebalancing when background tasks might be running
                    if (this.rebalanceCoordination.isRebalancing && this.config.waitForBackgroundTasksOnRebalance) {
                        if (
                            Date.now() - this.rebalanceCoordination.rebalanceStartTime >
                            this.rebalanceCoordination.rebalanceTimeoutMs
                        ) {
                            logger.error('🔁', 'rebalancing_timeout_forcing_recovery', {
                                rebalanceTimeoutMs: this.rebalanceCoordination.rebalanceTimeoutMs,
                                rebalanceStartTime: this.rebalanceCoordination.rebalanceStartTime,
                            })
                            this.rebalanceCoordination.isRebalancing = false
                        }
                        logger.info('🔁', 'main_loop_paused_for_rebalancing')
                        await new Promise((resolve) => setTimeout(resolve, 10)) // Small delay to avoid busy waiting
                        continue
                    }

                    const consumeStartTime = performance.now()
                    if (lastConsumeTime > 0) {
                        const intervalMs = consumeStartTime - lastConsumeTime
                        histogramKafkaConsumeInterval.labels({ topic, groupId }).observe(intervalMs)
                    }
                    lastConsumeTime = consumeStartTime
                    // TRICKY: We wrap this in a retry check. It seems that despite being connected and ready, the client can still have an undeterministic
                    // error when consuming, hence the retryIfRetriable.
                    const messages = await retryIfRetriable(() =>
                        promisifyCallback<Message[]>((cb) => this.rdKafkaConsumer.consume(this.fetchBatchSize, cb))
                    )

                    // After successfully pulling a batch, update heartbeat for backward compatibility
                    this.heartbeat()

                    gaugeBatchUtilization.labels({ groupId }).set(messages.length / this.fetchBatchSize)

                    logger.debug('🔁', 'main_loop_consumed', { messagesLength: messages.length })
                    histogramKafkaBatchSize.observe(messages.length)
                    histogramKafkaBatchSizeKb.observe(
                        messages.reduce((acc, m) => (m.value?.length ?? 0) + acc, 0) / 1024
                    )

                    if (!messages.length && !callEachBatchWhenEmpty) {
                        logger.debug('🔁', 'main_loop_empty_batch', { cause: 'empty' })
                        continue
                    }

                    const startProcessingTimeMs = new Date().valueOf()
                    const result = await eachBatch(messages)

                    const processingTimeMs = new Date().valueOf() - startProcessingTimeMs
                    consumedBatchDuration.labels({ topic, groupId }).observe(processingTimeMs)

                    const logSummary = `Processed ${messages.length} events in ${
                        Math.round(processingTimeMs / 10) / 100
                    }s`
                    if (processingTimeMs > SLOW_BATCH_PROCESSING_LOG_THRESHOLD_MS) {
                        logger.warn('🕒', `Slow batch: ${logSummary}, groupId: ${groupId}`)
                    }

                    // TRICKY: The commit logic needs to be aware of background work. If we were to just store offsets here,
                    // it would be hard to mix background work with non-background work.
                    // So we just create pretend work to simplify the rest of the logic
                    const backgroundTask = result?.backgroundTask ?? Promise.resolve()
                    const backgroundTaskStart = performance.now()
                    const taskCreatedAt = Date.now()
                    // Pull out the offsets to commit from the messages so we can release the messages reference
                    const topicPartitionOffsetsToCommit = findOffsetsToCommit(messages)

                    void backgroundTask.finally(async () => {
                        // Track that we made progress
                        this.lastBackgroundTaskCompletionTime = Date.now()

                        // First of all clear ourselves from the queue
                        const index = this.backgroundTask.findIndex((t) => t.promise === backgroundTask)

                        // CRITICAL: If task not found, this indicates some bigger problem
                        if (index < 0) {
                            captureException(new Error('Background task not found in array during cleanup'))
                            counterBackgroundTaskNotFound
                                .labels({ pod: this.podName, groupId: this.config.groupId })
                                .inc()
                        }

                        // TRICKY: We need to wait for all promises ahead of us in the queue before we store the offsets
                        // Important: capture the promises BEFORE removing the task, as the array changes after splice
                        if (index >= 0) {
                            // Task found - capture promises to wait for, then remove the task
                            const promisesToWait = this.backgroundTask.slice(0, index).map((t) => t.promise)
                            this.backgroundTask.splice(index, 1)
                            await Promise.all(promisesToWait)
                        }

                        if (this.config.autoCommit && this.config.autoOffsetStore) {
                            this.storeOffsetsForMessages(topicPartitionOffsetsToCommit)
                        }

                        if (result?.backgroundTask) {
                            // We only want to count the time spent in the background work if it was real
                            consumedBatchBackgroundDuration
                                .labels({
                                    topic: this.config.topic,
                                    groupId: this.config.groupId,
                                })
                                .observe(performance.now() - backgroundTaskStart)
                        }
                    })

                    // At first we just add the background work to the queue with metadata
                    this.backgroundTask.push({
                        promise: backgroundTask,
                        createdAt: taskCreatedAt,
                    })

                    // Update metrics
                    if (this.backgroundTask.length > 0) {
                        const oldestAge = Date.now() - this.backgroundTask[0].createdAt
                        gaugeOldestBackgroundTaskAge.labels({ pod: this.podName, groupId }).set(oldestAge)
                    } else {
                        gaugeOldestBackgroundTaskAge.labels({ pod: this.podName, groupId }).set(0)
                    }

                    const timeSinceProgress = Date.now() - this.lastBackgroundTaskCompletionTime
                    gaugeTimeSinceLastProgress.labels({ pod: this.podName, groupId }).set(timeSinceProgress)

                    // If we have too much "backpressure" we need to await one of the background tasks. We await the oldest one on purpose

                    if (this.backgroundTask.length >= this.maxBackgroundTasks) {
                        const stopTimer = consumedBatchBackpressureDuration.startTimer({
                            topic: this.config.topic,
                            groupId: this.config.groupId,
                        })
                        // If we have more than the max, we need to await one
                        await this.backgroundTask[0].promise
                        stopTimer()
                    }
                }

                // Once we are stopping, make sure that we wait for all background work to finish
                await Promise.all(this.backgroundTask.map((t) => t.promise))
            } catch (error) {
                throw error
            } finally {
                logger.info('🔁', 'main_loop_stopping')

                // Finally, disconnect from the broker. If stored offsets have changed via
                // `storeOffsetsForMessages` above, they will be committed before shutdown (so long
                // as this consumer is still part of the group).
                await this.disconnectConsumer()
                logger.info('🔁', 'Disconnected node-rdkafka consumer')
            }
        }

        this.consumerLoop = startConsuming().catch((error) => {
            logger.error('🔁', 'consumer_loop_error', {
                error: String(error),
                config: this.config,
                consumerConfig: this.consumerConfig,
            })
            // We re-throw the error as that way it will be caught in server.ts and trigger a full shutdown
            throw error
        })
    }

    public async disconnect(): Promise<void> {
        if (this.isStopping) {
            return
        }
        // Mark as stopping - this will also essentially stop the consumer loop
        this.isStopping = true

        // Wait for background tasks to complete before disconnecting
        logger.info('🔁', 'waiting_for_background_tasks_before_disconnect', {
            backgroundTaskCount: this.backgroundTask.length,
        })
        await Promise.all(this.backgroundTask.map((t) => t.promise))

        logger.info('🔁', 'background_tasks_completed_proceeding_with_disconnect')

        // Allow the in progress consumer loop to finish if possible
        if (this.consumerLoop) {
            await this.consumerLoop.catch((error) => {
                logger.error('🔁', 'failed to stop consumer loop safely. Continuing shutdown', {
                    error: String(error),
                    config: this.config,
                    consumerConfig: this.consumerConfig,
                })
            })
        }

        await this.disconnectConsumer()
    }

    private async disconnectConsumer(): Promise<void> {
        if (this.rdKafkaConsumer.isConnected()) {
            logger.info('📝', 'Disconnecting consumer...')
            await new Promise<void>((res, rej) => this.rdKafkaConsumer.disconnect((e) => (e ? rej(e) : res())))
            logger.info('📝', 'Disconnected consumer!')
        }
    }

    private resetRebalanceCoordination(): void {
        this.rebalanceCoordination.isRebalancing = false
        this.rebalanceCoordination.rebalanceStartTime = 0
    }
}

export const parseKafkaHeaders = (headers?: MessageHeader[]): Record<string, string> => {
    // Kafka headers come from librdkafka as an array of objects with keys value pairs per header.
    // It's a confusing format so we simplify it to a record.

    const result: Record<string, string> = {}

    headers?.forEach((header) => {
        Object.keys(header).forEach((key) => {
            result[key] = header[key].toString()
        })
    })

    return result
}

export const parseEventHeaders = (headers?: MessageHeader[]): EventHeaders => {
    // Kafka headers come from librdkafka as an array of objects with keys value pairs per header.
    // We extract the specific headers we care about into a structured format.

    const result: EventHeaders = {
        force_disable_person_processing: false,
    }

    headers?.forEach((header) => {
        Object.keys(header).forEach((key) => {
            const value = header[key].toString()
            if (key === 'token') {
                result.token = value
            } else if (key === 'distinct_id') {
                result.distinct_id = value
            } else if (key === 'timestamp') {
                result.timestamp = value
            } else if (key === 'event') {
                result.event = value
            } else if (key === 'uuid') {
                result.uuid = value
            } else if (key === 'force_disable_person_processing') {
                result.force_disable_person_processing = value === 'true'
            }
        })
    })

    // Track comprehensive header status metrics
    const trackedHeaders = [
        'token',
        'distinct_id',
        'timestamp',
        'event',
        'uuid',
        'force_disable_person_processing',
    ] as const
    trackedHeaders.forEach((header) => {
        const status = result[header] ? 'present' : 'absent'
        kafkaHeaderStatusCounter.labels(header, status).inc()
    })

    return result
}
