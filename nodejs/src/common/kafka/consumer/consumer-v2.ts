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

import { parseJSON } from '~/common/utils/json-parse'
import { HealthCheckResult, HealthCheckResultError, HealthCheckResultOk, LogLevel } from '~/types'

import { defaultConfig } from '../../config/config'
import { logger } from '../../utils/logger'
import { captureException } from '../../utils/posthog'
import { retryIfRetriable } from '../../utils/retries'
import { promisifyCallback } from '../../utils/utils'
import { ensureTopicExists } from '../admin'
import { getKafkaConfigFromEnv, stripClassicProtocolConfig } from '../config'
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
    consumerPolls,
    consumerStaleStoreOffsetsSkipped,
    kafkaConsumerAssignment,
} from './metrics'

const DEFAULT_BATCH_TIMEOUT_MS = 500
const STATISTICS_INTERVAL_MS = 5000
const LOOP_STALL_THRESHOLD_MS_DEFAULT = 60_000
// auto.offset.reset is a topic-level property and which config form librdkafka honors varies by
// version (see node-rdkafka #984), so it's applied to both the global config and the explicit
// topic config. This is the default when a consumer doesn't opt into an override.
const DEFAULT_AUTO_OFFSET_RESET = 'earliest'

export type KafkaConsumerV2Config = {
    groupId: string
    topic: string
    batchTimeoutMs?: number
    callEachBatchWhenEmpty?: boolean
    autoOffsetStore?: boolean
    autoCommit?: boolean
    enablePartitionEof?: boolean
    fetchBatchSize?: number
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
}

const partitionKey = (tp: { topic: string; partition: number }): string => `${tp.topic}/${tp.partition}`

/**
 * Single-coroutine Kafka consumer. The loop is the only mutator; the rebalance callback
 * just enqueues events. On REVOKE the loop synchronously drains in-flight settle promises
 * (post-storeOffsets, not raw user tasks), bumps the epoch of each partition it is giving up so
 * any laggard task skips its now-invalid storeOffsets for those partitions, runs the optional
 * onPartitionsRevoked hook while the partitions are still assigned (so a flush there can store
 * offsets that get committed on the unassign), then calls incrementalUnassign.
 */
export class KafkaConsumerV2 {
    private rdKafkaConsumer: RdKafkaConsumer
    private rdKafkaConfig: ConsumerGlobalConfig
    private podName: string
    private consumerId: string

    // Loop iterates while running; disconnect() flips it false.
    private running = true
    // Bumped for a partition each time we give it up, so a task that settles after that point
    // cannot store an offset for it. Keyed by `topic/partition`; absent means never revoked.
    private partitionEpochs = new Map<string, number>()
    // Rebalance counter, kept for log continuity only — the fence reads partitionEpochs.
    private generation = 0
    private rebalanceQueue: RebalanceEvent[] = []
    private inFlight: TaskEntry[] = []
    private loopDone: Promise<void> | undefined

    // Latched on the first backgroundTask failure: blocks further offset stores and
    // makes the loop exit on the next tick so the pod replays from the last good commit.
    private fatalError: unknown | undefined

    // Optional async hook invoked with the partitions being revoked, after the in-flight
    // drain and while the partitions are still assigned, before the unassign. The drain and
    // the hook share one budget (drainTimeoutMs): the hook gets whatever the drain left, and
    // a hook outliving it is abandoned so the rebalance proceeds. Not invoked for the final
    // revoke during disconnect — callers flush explicitly before disconnecting.
    private onPartitionsRevoked?: (assignments: Assignment[]) => Promise<void>

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

        this.fetchBatchSize = config.fetchBatchSize ?? defaultConfig.CONSUMER_BATCH_SIZE
        this.batchTimeoutMs = this.config.batchTimeoutMs ?? DEFAULT_BATCH_TIMEOUT_MS
        this.maxBackgroundTasks = defaultConfig.CONSUMER_MAX_BACKGROUND_TASKS
        this.backgroundTaskTimeoutMs = defaultConfig.CONSUMER_BACKGROUND_TASK_TIMEOUT_MS
        this.drainTimeoutMs = defaultConfig.CONSUMER_REBALANCE_TIMEOUT_MS
        this.loopStallThresholdMs = defaultConfig.CONSUMER_LOOP_STALL_THRESHOLD_MS || LOOP_STALL_THRESHOLD_MS_DEFAULT
        this.logStatsLevel = defaultConfig.CONSUMER_LOG_STATS_LEVEL

        this.rdKafkaConfig = stripClassicProtocolConfig({
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
            // Global/default-topic-conf fallback; the resolved value (incl. any override) is
            // also applied to the explicit topic config in createConsumer.
            ['auto.offset.reset' as keyof ConsumerGlobalConfig]: DEFAULT_AUTO_OFFSET_RESET as never,
            ...getKafkaConfigFromEnv('CONSUMER'),
            ...rdKafkaOverrides,
            // Settings we don't allow callers to override.
            'partition.assignment.strategy': 'cooperative-sticky',
            'enable.auto.offset.store': false,
            'enable.auto.commit': this.config.autoCommit,
            rebalance_cb: this.rebalanceCallback.bind(this),
            offset_commit_cb: true,
        })

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

    public async connect(
        eachBatch: EachBatch,
        onPartitionsRevoked?: (assignments: Assignment[]) => Promise<void>
    ): Promise<void> {
        this.onPartitionsRevoked = onPartitionsRevoked
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

    /**
     * Stop the consume loop and drain in-flight batches without leaving the group. After this
     * resolves, eachBatch will never be called again. Callers that buffer work across batches
     * flush and store offsets between this and disconnect(), which then commits the stored
     * offsets as it leaves the group — that ordering is what makes the final flush race-free.
     */
    public async stopConsuming(): Promise<void> {
        // Flip running so the loop exits and so the final REVOKE during disconnect goes
        // through rebalanceCallback's special-case path.
        this.running = false
        if (this.loopDone) {
            await this.loopDone.catch((error) => {
                logger.error('🔁', 'kafka_consumer_v2_loop_failed_during_disconnect', { error: String(error) })
            })
        }
    }

    public async disconnect(): Promise<void> {
        await this.stopConsuming()
        if (this.rdKafkaConsumer.isConnected()) {
            await new Promise<void>((res, rej) => this.rdKafkaConsumer.disconnect((e) => (e ? rej(e) : res())))
        }
    }

    // === Main loop ===

    private async runLoop(eachBatch: EachBatch): Promise<void> {
        try {
            while (this.running) {
                this.lastLoopTickAt = Date.now()

                // Check before fetching another batch — any further offset commit after a
                // task failure is the silent-drop bug.
                if (this.fatalError) {
                    throw this.fatalError
                }

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

        consumerPolls.labels(this.config.topic, this.config.groupId).inc()
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

        // We always track. If a partition backing this batch is revoked while eachBatch runs, the
        // epoch captured in trackTask makes that partition's storeOffsets a no-op, but inFlight
        // still holds the entry so drainAll waits for it.
        const offsets = findOffsetsToCommit(messages)
        this.trackTask(result, offsets)
        await this.applyBackpressure()
    }

    private trackTask(result: EachBatchResult, offsets: TopicPartitionOffset[]): void {
        const raw = result?.backgroundTask ?? Promise.resolve()
        const stopBackgroundTimer = result?.backgroundTask
            ? consumedBatchBackgroundDuration.startTimer({
                  topic: this.config.topic,
                  groupId: this.config.groupId,
              })
            : undefined

        // The epoch each partition held when this batch was dispatched. At store time an unchanged
        // epoch means we have held the partition continuously since, so the offset is still ours
        // to advance.
        const dispatchEpochs = new Map(offsets.map((o) => [partitionKey(o), this.epochOf(o)]))

        // Serialize store decisions in batch order: without this a faster later batch
        // could store its (higher) offset before an earlier failed batch latches fatalError.
        const predecessorSettled =
            this.inFlight.length > 0 ? this.inFlight[this.inFlight.length - 1].settled : undefined

        const settled: Promise<void> = (async () => {
            try {
                const { timedOut } = await raceWithTimeout(Promise.resolve(raw), this.backgroundTaskTimeoutMs)
                if (timedOut) {
                    throw new Error(`background_task_timeout_after_${this.backgroundTaskTimeoutMs}ms`)
                }
            } catch (error) {
                logger.error('🔥', 'kafka_consumer_v2_background_task_failed', { error: String(error) })
                captureException(error)
                this.fatalError ??= error
            } finally {
                stopBackgroundTimer?.()
            }

            if (predecessorSettled) {
                await predecessorSettled
            }

            if (this.fatalError) {
                return
            }

            if (this.config.autoCommit && this.config.autoOffsetStore) {
                // Fence per partition, not per rebalance. A partition we still hold is safe to
                // advance even if a sibling partition was revoked in the meantime; one that was
                // revoked is not, because it may have passed through another member since — and
                // storing our older offset would rewind the group and redeliver.
                const storable = offsets.filter((o) => this.epochOf(o) === dispatchEpochs.get(partitionKey(o)))
                const fenced = offsets.length - storable.length
                if (fenced > 0) {
                    consumerStaleStoreOffsetsSkipped.labels(this.config.topic, this.config.groupId).inc(fenced)
                }
                if (storable.length > 0) {
                    this.storeOffsetsInternal(storable)
                }
            }
        })()

        const entry: TaskEntry = { settled }
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
            // Ticks as the rebalance starts so both log lines below carry the same number. This
            // counter is only ever read by those two lines — the fence is the partitionEpochs bump
            // after the drain, and it deliberately does not happen this early.
            this.generation++
            logger.info('🔁', 'kafka_consumer_v2_revoke_starting', {
                inFlight: this.inFlight.length,
                generation: this.generation,
                partitions: event.partitions.map((p) => `${p.topic}/${p.partition}`),
            })
            // One budget for the whole revoke path: the drain spends what it needs and the
            // hook gets the remainder, so CONSUMER_REBALANCE_TIMEOUT_MS bounds the total hold
            // on the rebalance — not each phase separately.
            const revokeDeadline = Date.now() + this.drainTimeoutMs
            // Drain before fencing. A batch that settles inside the budget has already run its
            // side effects and still holds its partitions, so its offset store is valid and
            // librdkafka commits it on the unassign below. Fencing first discarded those offsets,
            // so the next owner replayed work that was already done — for a CDP destination that
            // is a second outbound request (duplicate Slack message, webhook, CRM write).
            await this.drainAll('revoke')
            // Whatever is still unsettled missed the budget: fence the partitions we are giving up
            // so a late settle can't store offsets for them. Partitions we keep are untouched, so
            // a laggard task can still commit the progress it made on those.
            for (const tp of event.partitions) {
                this.partitionEpochs.set(partitionKey(tp), this.epochOf(tp) + 1)
            }

            if (this.onPartitionsRevoked) {
                const hookBudgetMs = Math.max(revokeDeadline - Date.now(), 0)
                try {
                    // A wedged flush (e.g. a produce stuck until its delivery timeout) must not
                    // hold the group's rebalance hostage until max.poll.interval.ms fences the
                    // member. On timeout the partitions are given up without the flush's
                    // offsets — the new owner replays from the last commit, exactly as with a
                    // failed flush.
                    const { timedOut } = await raceWithTimeout(this.onPartitionsRevoked(event.partitions), hookBudgetMs)
                    if (timedOut) {
                        consumerDrainTimeouts.labels(this.config.topic, this.config.groupId, 'revoke_hook').inc()
                        logger.error('🔁', 'kafka_consumer_v2_revoke_handler_timeout', {
                            hookBudgetMs,
                            rebalanceTimeoutMs: this.drainTimeoutMs,
                        })
                    }
                } catch (error) {
                    // A failed flush must not strand the rebalance — give the partitions up
                    // anyway. The offsets simply won't have been stored, so the new owner
                    // reprocesses from the last commit.
                    logger.error('🔁', 'kafka_consumer_v2_revoke_handler_failed', { error: String(error) })
                    captureException(error)
                }
            }

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

    private epochOf(tp: { topic: string; partition: number }): number {
        return this.partitionEpochs.get(partitionKey(tp)) ?? 0
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
        // Mirror the resolved auto.offset.reset (incl. any override) into the explicit topic
        // config — the form librdkafka honors on our version. See DEFAULT_AUTO_OFFSET_RESET.
        const autoOffsetReset =
            (this.rdKafkaConfig['auto.offset.reset' as keyof ConsumerGlobalConfig] as
                | 'earliest'
                | 'latest'
                | undefined) ?? DEFAULT_AUTO_OFFSET_RESET
        const consumer = new RdKafkaConsumer(this.rdKafkaConfig, { 'auto.offset.reset': autoOffsetReset })

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
