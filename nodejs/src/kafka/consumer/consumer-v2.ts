import {
    Assignment,
    CODES,
    ClientMetrics,
    ConsumerGlobalConfig,
    LibrdKafkaError,
    Message,
    Metadata,
    KafkaConsumer as RdKafkaConsumer,
    TopicPartitionOffset,
} from 'node-rdkafka'
import { hostname } from 'os'

import { HealthCheckResult, HealthCheckResultError, HealthCheckResultOk, LogLevel } from '~/types'
import { parseJSON } from '~/utils/json-parse'

import { defaultConfig } from '../../config/config'
import { logger } from '../../utils/logger'
import { captureException } from '../../utils/posthog'
import { retryIfRetriable } from '../../utils/retries'
import { promisifyCallback } from '../../utils/utils'
import { ensureTopicExists } from '../admin'
import { getKafkaConfigFromEnv } from '../config'
import { parseBrokerStatistics, trackBrokerMetrics } from '../kafka-client-metrics'
import {
    consumedBatchBackgroundDuration,
    consumedBatchBackpressureDuration,
    consumedBatchDuration,
    consumerBatchSize,
    consumerBatchSizeKb,
    consumerBatchUtilization,
    consumerDrainDuration,
    consumerDrainTimeouts,
    consumerStaleStoreOffsetsSkipped,
    kafkaConsumerAssignment,
} from './metrics'

const DEFAULT_BATCH_TIMEOUT_MS = 500
const STATISTICS_INTERVAL_MS = 5000
const LOOP_STALL_THRESHOLD_MS_DEFAULT = 60_000

export type KafkaConsumerV2Config = {
    groupId: string
    topic: string
    batchTimeoutMs?: number
    callEachBatchWhenEmpty?: boolean
    autoOffsetStore?: boolean
    autoCommit?: boolean
    enablePartitionEof?: boolean
}

export type RdKafkaConsumerOverrides = Omit<
    ConsumerGlobalConfig,
    'group.id' | 'enable.auto.offset.store' | 'enable.auto.commit'
>

export type EachBatchResult = { backgroundTask?: Promise<unknown> } | void
export type EachBatch = (messages: Message[]) => Promise<EachBatchResult>

type RebalanceEvent =
    | { type: 'ASSIGN'; partitions: Assignment[] }
    | { type: 'REVOKE'; partitions: Assignment[] }
    | { type: 'ERROR'; err: LibrdKafkaError }

type TaskEntry = {
    settled: Promise<void>
    generation: number
}

/**
 * Single-coroutine Kafka consumer. The loop is the only mutator; the rebalance callback
 * just enqueues events. On REVOKE the loop synchronously drains in-flight settle promises
 * (post-storeOffsets, not raw user tasks), bumps `generation` so any laggard task skips
 * its now-invalid storeOffsets, then calls incrementalUnassign.
 */
export class KafkaConsumerV2 {
    private rdKafkaConsumer: RdKafkaConsumer
    private rdKafkaConfig: ConsumerGlobalConfig
    private podName: string
    private consumerId: string

    // Loop iterates while running; disconnect() flips it false.
    private running = true
    private generation = 0
    private rebalanceQueue: RebalanceEvent[] = []
    private inFlight: TaskEntry[] = []
    private loopDone: Promise<void> | undefined

    // Tunables (resolved at construction)
    private fetchBatchSize: number
    private batchTimeoutMs: number
    private maxBackgroundTasks: number
    private backgroundTaskTimeoutMs: number
    private drainTimeoutMs: number
    private loopStallThresholdMs: number
    private logStatsLevel: LogLevel

    // Health tracking
    private lastLoopTickAt = 0

    constructor(
        private config: KafkaConsumerV2Config,
        rdKafkaOverrides: RdKafkaConsumerOverrides = {}
    ) {
        this.config.autoCommit ??= true
        this.config.autoOffsetStore ??= true
        this.config.callEachBatchWhenEmpty ??= false

        this.podName = process.env.HOSTNAME || hostname()
        this.consumerId = `${this.podName}-${this.config.groupId}-${Date.now()}-${Math.random()
            .toString(36)
            .substring(2, 8)}`

        this.fetchBatchSize = defaultConfig.CONSUMER_BATCH_SIZE
        this.batchTimeoutMs = this.config.batchTimeoutMs ?? DEFAULT_BATCH_TIMEOUT_MS
        this.maxBackgroundTasks = defaultConfig.CONSUMER_MAX_BACKGROUND_TASKS
        this.backgroundTaskTimeoutMs = defaultConfig.CONSUMER_BACKGROUND_TASK_TIMEOUT_MS
        this.drainTimeoutMs = defaultConfig.CONSUMER_REBALANCE_TIMEOUT_MS
        this.loopStallThresholdMs = defaultConfig.CONSUMER_LOOP_STALL_THRESHOLD_MS || LOOP_STALL_THRESHOLD_MS_DEFAULT
        this.logStatsLevel = defaultConfig.CONSUMER_LOG_STATS_LEVEL

        this.rdKafkaConfig = {
            'client.id': hostname(),
            'security.protocol': 'plaintext',
            'metadata.broker.list': 'kafka:9092',
            log_level: 4,
            'group.id': this.config.groupId,
            'session.timeout.ms': 30_000,
            'max.poll.interval.ms': 300_000,
            'max.partition.fetch.bytes': 1_048_576,
            'fetch.error.backoff.ms': 100,
            'fetch.message.max.bytes': 10_485_760,
            'fetch.wait.max.ms': 50,
            'queued.min.messages': 100_000,
            'queued.max.messages.kbytes': 102_400,
            'client.rack': defaultConfig.KAFKA_CLIENT_RACK,
            'metadata.max.age.ms': 30_000,
            'socket.timeout.ms': 30_000,
            'enable.partition.eof': this.config.enablePartitionEof ?? true,
            'statistics.interval.ms': STATISTICS_INTERVAL_MS,
            // Newer librdkafka versions require this in the global config (the topic-config
            // form passed to RdKafkaConsumer's second arg is silently ignored for assign-based
            // consumers in some versions). See node-rdkafka issue #984.
            ['auto.offset.reset' as keyof ConsumerGlobalConfig]: 'earliest' as never,
            ...getKafkaConfigFromEnv('CONSUMER'),
            ...rdKafkaOverrides,
            // Settings we don't allow callers to override.
            'partition.assignment.strategy': 'cooperative-sticky',
            'enable.auto.offset.store': false,
            'enable.auto.commit': this.config.autoCommit,
            rebalance_cb: this.rebalanceCallback.bind(this),
            offset_commit_cb: true,
        }

        this.rdKafkaConsumer = this.createConsumer()
    }

    public isHealthy(): HealthCheckResult {
        if (!this.rdKafkaConsumer.isConnected()) {
            return new HealthCheckResultError('Consumer not connected to Kafka broker', {
                topic: this.config.topic,
                groupId: this.config.groupId,
            })
        }

        const timeSinceLastTick = this.lastLoopTickAt > 0 ? Date.now() - this.lastLoopTickAt : 0
        if (this.lastLoopTickAt > 0 && timeSinceLastTick > this.loopStallThresholdMs) {
            return new HealthCheckResultError(
                `Consumer loop stalled (no tick for ${Math.round(timeSinceLastTick / 1000)}s)`,
                {
                    topic: this.config.topic,
                    groupId: this.config.groupId,
                    running: this.running,
                    timeSinceLastTick,
                    threshold: this.loopStallThresholdMs,
                }
            )
        }

        return new HealthCheckResultOk()
    }

    public assignments(): Assignment[] {
        return this.rdKafkaConsumer.isConnected() ? this.rdKafkaConsumer.assignments() : []
    }

    public offsetsStore(offsets: TopicPartitionOffset[]): void {
        // Manual offset path used by SessionRecording. Storing offsets after the consumer
        // has revoked the partitions is harmless — librdkafka will reject the store internally.
        this.rdKafkaConsumer.offsetsStore(offsets)
    }

    public async connect(eachBatch: EachBatch): Promise<void> {
        try {
            await promisifyCallback<Metadata>((cb) => this.rdKafkaConsumer.connect({}, cb))
            logger.info('📝', 'kafka_consumer_v2_connected', { groupId: this.config.groupId, topic: this.config.topic })
        } catch (error) {
            logger.error('⚠️', 'kafka_consumer_v2_connect_error', { error })
            throw error
        }

        if (defaultConfig.CONSUMER_AUTO_CREATE_TOPICS) {
            await ensureTopicExists(this.rdKafkaConfig, this.config.topic)
        }

        this.rdKafkaConsumer.setDefaultConsumeTimeout(this.batchTimeoutMs)
        this.rdKafkaConsumer.subscribe([this.config.topic])

        this.lastLoopTickAt = Date.now()
        this.loopDone = this.runLoop(eachBatch).catch((error) => {
            logger.error('🔁', 'kafka_consumer_v2_loop_error', {
                error: String(error),
                groupId: this.config.groupId,
                topic: this.config.topic,
            })
            throw error
        })
    }

    public async disconnect(): Promise<void> {
        if (!this.running) {
            return
        }
        // Flip running so the loop exits and so the final REVOKE during disconnect goes
        // through rebalanceCallback's special-case path.
        this.running = false
        if (this.loopDone) {
            await this.loopDone.catch((error) => {
                logger.error('🔁', 'kafka_consumer_v2_loop_failed_during_disconnect', { error: String(error) })
            })
        }
        if (this.rdKafkaConsumer.isConnected()) {
            await new Promise<void>((res, rej) => this.rdKafkaConsumer.disconnect((e) => (e ? rej(e) : res())))
        }
    }

    // === Main loop ===

    private async runLoop(eachBatch: EachBatch): Promise<void> {
        try {
            while (this.running) {
                this.lastLoopTickAt = Date.now()

                // 1. Drain rebalance events. handleRebalanceEvent on REVOKE awaits drainAll
                // and calls incrementalUnassign before returning.
                while (this.rebalanceQueue.length > 0) {
                    const event = this.rebalanceQueue.shift()!
                    await this.handleRebalanceEvent(event)
                    if (!this.running) {
                        break
                    }
                }
                if (!this.running) {
                    break
                }

                // 2. Poll. consume() also drives heartbeats / rebalance delivery; with no
                // assignments it returns empty within fetch.wait.max.ms.
                await this.fetchAndDispatch(eachBatch)
            }
        } finally {
            // Drain whatever is left before letting the caller's disconnect() return.
            await this.drainAll('shutdown')
        }
    }

    private async fetchAndDispatch(eachBatch: EachBatch): Promise<void> {
        const messages = await retryIfRetriable(() =>
            promisifyCallback<Message[]>((cb) => this.rdKafkaConsumer.consume(this.fetchBatchSize, cb))
        )

        consumerBatchSize.observe(messages.length)
        consumerBatchSizeKb.observe(messages.reduce((acc, m) => (m.value?.length ?? 0) + acc, 0) / 1024)
        consumerBatchUtilization.labels({ groupId: this.config.groupId }).set(messages.length / this.fetchBatchSize)

        if (messages.length === 0 && !this.config.callEachBatchWhenEmpty) {
            return
        }

        // disconnect() may have flipped `running` while we were awaiting consume().
        if (!this.running) {
            return
        }

        const startMs = Date.now()
        // eachBatch errors are intentionally NOT caught — they propagate to the loop and
        // crash the process. At-least-once is preserved (uncommitted offsets get re-read
        // on restart) and any logic bug surfaces loudly rather than silently dropping.
        const result: EachBatchResult = await eachBatch(messages)
        consumedBatchDuration.labels(this.config.topic, this.config.groupId).observe(Date.now() - startMs)

        // We always track. If a REVOKE arrived while eachBatch ran, the generation tag in
        // trackTask makes the storeOffsets a no-op, but inFlight still holds the entry so
        // drainAll waits for it.
        const offsets = findOffsetsToCommit(messages)
        this.trackTask(result, offsets, this.generation)
        await this.applyBackpressure()
    }

    private trackTask(result: EachBatchResult, offsets: TopicPartitionOffset[], gen: number): void {
        const raw = result?.backgroundTask ?? Promise.resolve()
        const stopBackgroundTimer = result?.backgroundTask
            ? consumedBatchBackgroundDuration.startTimer({
                  topic: this.config.topic,
                  groupId: this.config.groupId,
              })
            : undefined

        const settled: Promise<void> = (async () => {
            try {
                const { timedOut } = await raceWithTimeout(Promise.resolve(raw), this.backgroundTaskTimeoutMs)
                if (timedOut) {
                    throw new Error(`background_task_timeout_after_${this.backgroundTaskTimeoutMs}ms`)
                }
            } catch (error) {
                logger.error('🔥', 'kafka_consumer_v2_background_task_failed', { error: String(error) })
                captureException(error)
                // Do not store offsets when the task failed.
                return
            } finally {
                stopBackgroundTimer?.()
            }

            if (this.config.autoCommit && this.config.autoOffsetStore) {
                if (gen !== this.generation) {
                    // The partitions backing these offsets were revoked between dispatch and now.
                    // Skip the store — librdkafka would reject it anyway after unassign.
                    consumerStaleStoreOffsetsSkipped.labels(this.config.topic, this.config.groupId).inc(offsets.length)
                    return
                }
                this.storeOffsetsInternal(offsets)
            }
        })()

        const entry: TaskEntry = { settled, generation: gen }
        this.inFlight.push(entry)
        // Self-cleanup so steady-state inFlight doesn't grow unbounded.
        void settled.finally(() => {
            const idx = this.inFlight.indexOf(entry)
            if (idx >= 0) {
                this.inFlight.splice(idx, 1)
            }
        })
    }

    private async applyBackpressure(): Promise<void> {
        if (this.inFlight.length < this.maxBackgroundTasks) {
            return
        }
        const stop = consumedBatchBackpressureDuration.startTimer({
            topic: this.config.topic,
            groupId: this.config.groupId,
        })
        try {
            // Wait for the OLDEST task's settled chain. Using settled (not raw) means we don't
            // release backpressure until storeOffsets has been attempted.
            await this.inFlight[0].settled
        } finally {
            stop()
        }
    }

    private async handleRebalanceEvent(event: RebalanceEvent): Promise<void> {
        if (event.type === 'ASSIGN') {
            try {
                if (this.rdKafkaConsumer.rebalanceProtocol() === 'COOPERATIVE') {
                    this.rdKafkaConsumer.incrementalAssign(event.partitions)
                } else {
                    this.rdKafkaConsumer.assign(event.partitions)
                }
            } catch (error) {
                logger.error('🔁', 'kafka_consumer_v2_assign_failed', { error: String(error) })
                captureException(error)
                return
            }
            for (const tp of event.partitions) {
                kafkaConsumerAssignment
                    .labels({
                        topic_name: tp.topic,
                        partition_id: tp.partition.toString(),
                        pod: this.podName,
                        group_id: this.config.groupId,
                    })
                    .set(1)
            }
            logger.info('🔁', 'kafka_consumer_v2_assigned', {
                partitions: event.partitions.map((p) => `${p.topic}/${p.partition}`),
            })
            return
        }

        if (event.type === 'REVOKE') {
            this.generation++
            logger.info('🔁', 'kafka_consumer_v2_revoke_starting', {
                inFlight: this.inFlight.length,
                generation: this.generation,
                partitions: event.partitions.map((p) => `${p.topic}/${p.partition}`),
            })
            await this.drainAll('revoke')

            try {
                if (this.rdKafkaConsumer.rebalanceProtocol() === 'COOPERATIVE') {
                    this.rdKafkaConsumer.incrementalUnassign(event.partitions)
                } else {
                    this.rdKafkaConsumer.unassign()
                }
            } catch (error) {
                logger.error('🔁', 'kafka_consumer_v2_unassign_failed', { error: String(error) })
                captureException(error)
            }

            for (const tp of event.partitions) {
                kafkaConsumerAssignment
                    .labels({
                        topic_name: tp.topic,
                        partition_id: tp.partition.toString(),
                        pod: this.podName,
                        group_id: this.config.groupId,
                    })
                    .set(0)
            }
            const remaining = this.rdKafkaConsumer.isConnected() ? this.rdKafkaConsumer.assignments() : []
            logger.info('🔁', 'kafka_consumer_v2_revoke_complete', {
                generation: this.generation,
                remainingAssignments: remaining.length,
            })
            return
        }

        // ERROR
        if (this.rdKafkaConsumer.isConnected()) {
            logger.error('🔥', 'kafka_consumer_v2_rebalance_error', { err: event.err })
            captureException(event.err)
        } else {
            logger.warn('🔥', 'kafka_consumer_v2_rebalance_error_while_disconnected', { err: event.err })
        }
    }

    private async drainAll(cause: 'revoke' | 'shutdown'): Promise<void> {
        if (this.inFlight.length === 0) {
            return
        }
        const stop = consumerDrainDuration.labels(this.config.topic, this.config.groupId, cause).startTimer()
        // Snapshot at drain time — entries added AFTER this point are excluded by design;
        // they were created in the next generation and have nothing to drain for THIS rebalance.
        const promises = this.inFlight.map((t) => t.settled)
        let timedOut = false
        try {
            const result = await raceWithTimeout(Promise.all(promises), this.drainTimeoutMs)
            timedOut = result.timedOut
        } finally {
            stop()
        }
        if (timedOut) {
            consumerDrainTimeouts.labels(this.config.topic, this.config.groupId, cause).inc()
            logger.error('🔁', 'kafka_consumer_v2_drain_timeout', {
                cause,
                drainTimeoutMs: this.drainTimeoutMs,
                inFlight: this.inFlight.length,
            })
        }
    }

    private storeOffsetsInternal(offsets: TopicPartitionOffset[]): void {
        if (offsets.length === 0) {
            return
        }
        try {
            this.rdKafkaConsumer.offsetsStore(offsets)
        } catch (error) {
            // Expected when partitions were revoked between batch dispatch and offset store.
            logger.warn('📝', 'kafka_consumer_v2_store_offsets_failed', {
                error: String(error),
                offsets,
            })
        }
    }

    // === Rebalance callback — pure event source, mutates nothing except the queue ===

    private rebalanceCallback(err: LibrdKafkaError, partitions: Assignment[]): void {
        // Special case: during disconnect, librdkafka delivers a final REVOKE and waits
        // for the application to call unassign() synchronously. The loop has already
        // exited at this point, so we have to handle it inline rather than enqueue.
        if (!this.running) {
            if (err.code === CODES.ERRORS.ERR__REVOKE_PARTITIONS) {
                try {
                    if (this.rdKafkaConsumer.rebalanceProtocol() === 'COOPERATIVE') {
                        this.rdKafkaConsumer.incrementalUnassign(partitions)
                    } else {
                        this.rdKafkaConsumer.unassign()
                    }
                } catch (error) {
                    logger.warn('🔁', 'kafka_consumer_v2_unassign_during_shutdown_failed', {
                        error: String(error),
                    })
                }
            }
            return
        }

        if (err.code === CODES.ERRORS.ERR__ASSIGN_PARTITIONS) {
            this.rebalanceQueue.push({ type: 'ASSIGN', partitions })
        } else if (err.code === CODES.ERRORS.ERR__REVOKE_PARTITIONS) {
            this.rebalanceQueue.push({ type: 'REVOKE', partitions })
        } else {
            this.rebalanceQueue.push({ type: 'ERROR', err })
        }
    }

    // === RdKafkaConsumer construction + event wiring ===

    private createConsumer(): RdKafkaConsumer {
        const consumer = new RdKafkaConsumer(this.rdKafkaConfig, { 'auto.offset.reset': 'earliest' })

        consumer.on('event.log', (log) => logger.info('📝', 'kafka_consumer_v2_librdkafka_log', { log }))
        consumer.on('event.error', (error: LibrdKafkaError) => {
            // librdkafka emits transient errors (local timeouts during pod churn, broker
            // disconnects, metadata refresh failures) on the same channel as fatal errors.
            // Only escalate when it's actually fatal — otherwise this is informational noise
            // that floods on every deployment restart.
            const level = error.isFatal ? 'error' : 'warn'
            logger[level]('📝', 'kafka_consumer_v2_librdkafka_error', { error })
        })
        consumer.on('event.stats', (stats: { message: string }) => {
            try {
                const parsed = parseJSON(stats.message) as Record<string, any>
                const brokerStats = parseBrokerStatistics(parsed)
                trackBrokerMetrics(brokerStats, this.config.groupId, this.consumerId)
                logger[this.logStatsLevel]('📊', 'kafka_consumer_v2_stats', {
                    rx_msgs: parsed.rxmsgs,
                    rx_bytes: parsed.rx_bytes ?? parsed.rxbytes,
                    consumer_group_state: parsed.cgrp?.state,
                    rebalance_state: parsed.cgrp?.join_state,
                    rebalance_cnt: parsed.cgrp?.rebalance_cnt,
                    assignment_size: parsed.cgrp?.assignment_size,
                })
            } catch (error) {
                logger.error('📊', 'kafka_consumer_v2_stats_parse_failed', { error: String(error) })
            }
        })
        consumer.on('subscribed', (topics) => logger.info('📝', 'kafka_consumer_v2_subscribed', { topics }))
        consumer.on('connection.failure', (error: LibrdKafkaError, metrics: ClientMetrics) =>
            logger.error('📝', 'kafka_consumer_v2_connection_failure', { error, metrics })
        )
        consumer.on('offset.commit', (error: LibrdKafkaError, offsets: TopicPartitionOffset[]) => {
            if (error) {
                logger.warn('📝', 'kafka_consumer_v2_offset_commit_error', { error, offsets })
            } else {
                logger.debug('📝', 'kafka_consumer_v2_offset_commit', { offsets })
            }
        })

        return consumer
    }
}

/**
 * Race `p` against a timeout. Unlike `Promise.race([p, sleep(ms).then(...)])`, this clears
 * the timer when `p` settles first so we don't leak a pending setTimeout into the event loop.
 */
function raceWithTimeout<T>(p: Promise<T>, ms: number): Promise<{ value?: T; timedOut: boolean }> {
    return new Promise((resolve, reject) => {
        const timer = setTimeout(() => resolve({ timedOut: true }), ms)
        p.then(
            (v) => {
                clearTimeout(timer)
                resolve({ value: v, timedOut: false })
            },
            (e) => {
                clearTimeout(timer)
                reject(e)
            }
        )
    })
}

/** For each (topic, partition) in `messages`, return the next offset to commit (highest seen + 1). */
function findOffsetsToCommit(messages: TopicPartitionOffset[]): TopicPartitionOffset[] {
    const grouped = new Map<string, Map<number, number>>()
    for (const m of messages) {
        let byPartition = grouped.get(m.topic)
        if (!byPartition) {
            byPartition = new Map<number, number>()
            grouped.set(m.topic, byPartition)
        }
        const current = byPartition.get(m.partition)
        if (current === undefined || m.offset > current) {
            byPartition.set(m.partition, m.offset)
        }
    }
    const result: TopicPartitionOffset[] = []
    for (const [topic, byPartition] of grouped) {
        for (const [partition, highest] of byPartition) {
            result.push({ topic, partition, offset: highest + 1 })
        }
    }
    return result
}
