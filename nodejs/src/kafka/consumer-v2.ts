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
import { Counter, Gauge, Histogram } from 'prom-client'

import { HealthCheckResult, HealthCheckResultError, HealthCheckResultOk, LogLevel } from '~/types'
import { isTestEnv } from '~/utils/env-utils'
import { parseJSON } from '~/utils/json-parse'

import { defaultConfig } from '../config/config'
import { logger } from '../utils/logger'
import { captureException } from '../utils/posthog'
import { retryIfRetriable } from '../utils/retries'
import { promisifyCallback } from '../utils/utils'
import { ensureTopicExists } from './admin'
import { getKafkaConfigFromEnv } from './config'
import { parseBrokerStatistics, trackBrokerMetrics } from './kafka-client-metrics'

const DEFAULT_BATCH_TIMEOUT_MS = 500
const DRAIN_KEEPALIVE_TIMEOUT_MS = 100 // short consume() during DRAINING to keep heartbeat alive
const IDLE_POLL_INTERVAL_MS = 100
const STATISTICS_INTERVAL_MS = 5000
const LOOP_STALL_THRESHOLD_MS_DEFAULT = 60_000

// All v2 metrics carry a `_v2` suffix so v1 and v2 can coexist in the same process during
// rollout. Dashboards should `OR` v1 and v2 names (or sum them) for the duration of the
// migration; once v1 is deleted, drop the suffix in a follow-up.
const consumerAssignment = new Gauge({
    name: 'kafka_consumer_assignment_v2',
    help: 'Kafka consumer partition assignment status (v2)',
    labelNames: ['topic_name', 'partition_id', 'pod', 'group_id'],
})

const consumedBatchDuration = new Histogram({
    name: 'consumed_batch_duration_ms_v2',
    help: 'Main loop consumer batch processing duration in ms (v2)',
    labelNames: ['topic', 'groupId'],
})

const consumedBatchBackgroundDuration = new Histogram({
    name: 'consumed_batch_background_duration_ms_v2',
    help: 'Background task processing duration in ms (v2)',
    labelNames: ['topic', 'groupId'],
})

const consumedBatchBackpressureDuration = new Histogram({
    name: 'consumed_batch_backpressure_duration_ms_v2',
    help: 'Time spent waiting for background work to finish due to backpressure (v2)',
    labelNames: ['topic', 'groupId'],
})

const consumerBatchSize = new Histogram({
    name: 'consumer_batch_size_v2',
    help: 'The size of the batches we are receiving from Kafka (v2)',
    buckets: [0, 50, 100, 250, 500, 750, 1000, 1500, 2000, 3000, Infinity],
})

const consumerBatchSizeKb = new Histogram({
    name: 'consumer_batch_size_kb_v2',
    help: 'The size in kb of the batches we are receiving from Kafka (v2)',
    buckets: [0, 128, 512, 1024, 5120, 10240, 20480, 51200, 102400, 204800, Infinity],
})

const consumerDrainDuration = new Histogram({
    name: 'kafka_consumer_drain_duration_ms_v2',
    help: 'Time spent draining in-flight tasks during a rebalance or shutdown (v2)',
    labelNames: ['topic', 'groupId', 'cause'],
    buckets: [10, 50, 100, 500, 1000, 5000, 10000, 30000, 60000, 120000, Infinity],
})

const consumerDrainTimeouts = new Counter({
    name: 'kafka_consumer_drain_timeouts_total_v2',
    help: 'Number of times a drain hit its timeout before all tasks settled (v2)',
    labelNames: ['topic', 'groupId', 'cause'],
})

const consumerStaleStoreOffsetsSkipped = new Counter({
    name: 'kafka_consumer_stale_store_offsets_skipped_total_v2',
    help: 'Number of times an offset store was skipped because the task spanned a rebalance generation (v2)',
    labelNames: ['topic', 'groupId'],
})

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

type State = 'IDLE' | 'CONSUMING' | 'DRAINING' | 'STOPPED'

type RebalanceEvent =
    | { type: 'ASSIGN'; partitions: Assignment[] }
    | { type: 'REVOKE'; partitions: Assignment[] }
    | { type: 'ERROR'; err: LibrdKafkaError }

type TaskEntry = {
    settled: Promise<void>
    generation: number
}

/**
 * KafkaConsumerV2 — single-coroutine consumer with deterministic rebalance handling.
 *
 * Design contract:
 *   - The main loop is the only mutator of state. The rebalance callback only enqueues events.
 *   - REVOKE → DRAINING → drain all in-flight settle promises → incrementalUnassign → IDLE.
 *   - drain awaits the post-storeOffsets chain (`settled`), not the raw user task.
 *   - tasks are only created in CONSUMING state, so no task is excluded from a drain snapshot.
 *
 * See plans/kafka-consumer-v2-rewrite.md for the full design + the H1/H2/H3 regressions
 * this is built to defeat.
 */
export class KafkaConsumerV2 {
    private rdKafkaConsumer: RdKafkaConsumer
    private rdKafkaConfig: ConsumerGlobalConfig
    private podName: string
    private consumerId: string

    // Loop control
    private state: State = 'IDLE'
    private generation = 0
    private rebalanceQueue: RebalanceEvent[] = []
    private inFlight: TaskEntry[] = []
    private loopDone: Promise<void> | undefined
    private wakeResolve: (() => void) | undefined

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
    private lastStatsAt = 0
    private brokerState: string | undefined

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
            ...getKafkaConfigFromEnv('CONSUMER'),
            ...rdKafkaOverrides,
            // Below are settings we DO NOT allow callers to override
            'partition.assignment.strategy': isTestEnv() ? 'roundrobin' : 'cooperative-sticky',
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
                    state: this.state,
                    timeSinceLastTick,
                    threshold: this.loopStallThresholdMs,
                }
            )
        }

        return new HealthCheckResultOk()
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
        if (this.state === 'STOPPED') {
            return
        }
        // Signal the loop to stop. The loop drains in-flight tasks before disconnecting.
        this.state = 'STOPPED'
        this.wake() // pull the loop out of IDLE if it was sleeping
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
            while ((this.state as State) !== 'STOPPED') {
                this.lastLoopTickAt = Date.now()

                // 1. Process all queued rebalance events synchronously, with awaits where needed.
                while (this.rebalanceQueue.length > 0) {
                    const event = this.rebalanceQueue.shift()!
                    await this.handleRebalanceEvent(event)
                    if ((this.state as State) === 'STOPPED') {
                        break
                    }
                }
                if ((this.state as State) === 'STOPPED') {
                    break
                }

                // 2. State-gated work
                if ((this.state as State) === 'CONSUMING') {
                    await this.fetchAndDispatch(eachBatch)
                } else if ((this.state as State) === 'DRAINING') {
                    // Should not reach here: handleRebalanceEvent transitions DRAINING → IDLE before returning.
                    // Defensive keepalive for safety.
                    await this.consumeKeepalive()
                } else {
                    // IDLE — librdkafka still drives heartbeats internally; sleep until a
                    // rebalance event arrives or the poll interval elapses.
                    await this.idleWait()
                }
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

        if (messages.length === 0 && !this.config.callEachBatchWhenEmpty) {
            return
        }

        // CRITICAL — re-check state after the await. A REVOKE may have arrived during consume();
        // we must NOT push a new task while DRAINING. Skip and let the rebalance event run next tick.
        if ((this.state as State) !== 'CONSUMING') {
            return
        }

        const startMs = Date.now()
        let result: EachBatchResult
        try {
            result = await eachBatch(messages)
        } catch (error) {
            logger.error('🔥', 'kafka_consumer_v2_each_batch_error', { error: String(error) })
            captureException(error)
            // Do not store offsets on failure. Loop continues to the next batch.
            return
        }
        consumedBatchDuration.labels(this.config.topic, this.config.groupId).observe(Date.now() - startMs)

        // Re-check state once more before tracking. Same reason: REVOKE during eachBatch.
        // If we transitioned to DRAINING, we still want this task tracked so it gets drained —
        // since `inFlight` is the source of truth for drainAll(). The generation tag ensures
        // its storeOffsets is skipped if the rebalance has already incremented generation.
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
                await Promise.race([
                    raw,
                    sleep(this.backgroundTaskTimeoutMs).then(() => {
                        throw new Error(`background_task_timeout_after_${this.backgroundTaskTimeoutMs}ms`)
                    }),
                ])
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
                consumerAssignment
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
            this.state = 'CONSUMING'
            return
        }

        if (event.type === 'REVOKE') {
            this.state = 'DRAINING'
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
                consumerAssignment
                    .labels({
                        topic_name: tp.topic,
                        partition_id: tp.partition.toString(),
                        pod: this.podName,
                        group_id: this.config.groupId,
                    })
                    .set(0)
            }
            logger.info('🔁', 'kafka_consumer_v2_revoke_complete', { generation: this.generation })

            // Stay in IDLE until librdkafka delivers the next ASSIGN (or never, if we're shutting down).
            this.state = 'IDLE'
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
            await Promise.race([
                Promise.all(promises),
                sleep(this.drainTimeoutMs).then(() => {
                    timedOut = true
                }),
            ])
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

    /** Block in IDLE until a rebalance event arrives, disconnect is requested, or timeout fires. */
    private async idleWait(): Promise<void> {
        await new Promise<void>((resolve) => {
            this.wakeResolve = resolve
            setTimeout(resolve, IDLE_POLL_INTERVAL_MS)
        })
        this.wakeResolve = undefined
    }

    private wake(): void {
        const r = this.wakeResolve
        this.wakeResolve = undefined
        r?.()
    }

    private async consumeKeepalive(): Promise<void> {
        // Fire-and-receive a tiny consume to keep max.poll.interval.ms healthy if a drain ever
        // outlasts the natural fetch cadence. Empty results are expected.
        try {
            await promisifyCallback<Message[]>((cb) => this.rdKafkaConsumer.consume(0, cb))
        } catch {
            // ignore — keepalive only
        }
        await sleep(DRAIN_KEEPALIVE_TIMEOUT_MS)
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
        if (err.code === CODES.ERRORS.ERR__ASSIGN_PARTITIONS) {
            this.rebalanceQueue.push({ type: 'ASSIGN', partitions })
        } else if (err.code === CODES.ERRORS.ERR__REVOKE_PARTITIONS) {
            this.rebalanceQueue.push({ type: 'REVOKE', partitions })
        } else {
            this.rebalanceQueue.push({ type: 'ERROR', err })
        }
        // Pull the loop out of IDLE immediately so the event is processed without waiting
        // for the next poll-interval tick.
        this.wake()
    }

    // === RdKafkaConsumer construction + event wiring ===

    private createConsumer(): RdKafkaConsumer {
        const consumer = new RdKafkaConsumer(this.rdKafkaConfig, { 'auto.offset.reset': 'earliest' })

        consumer.on('event.log', (log) => logger.info('📝', 'kafka_consumer_v2_librdkafka_log', { log }))
        consumer.on('event.error', (error: LibrdKafkaError) =>
            logger.error('📝', 'kafka_consumer_v2_librdkafka_error', { error })
        )
        consumer.on('event.stats', (stats: { message: string }) => {
            try {
                const parsed = parseJSON(stats.message) as Record<string, any>
                this.lastStatsAt = Date.now()
                this.brokerState = parsed.cgrp?.state ?? 'no-group'
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

function sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms))
}

/**
 * For each (topic, partition) in `messages`, return the next offset to commit
 * (highest seen + 1). Pure function — kept here to avoid pulling v1's metrics
 * via a module-level import.
 */
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
