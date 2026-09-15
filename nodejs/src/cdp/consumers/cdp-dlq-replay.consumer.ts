import { Message } from 'node-rdkafka'
import { Counter } from 'prom-client'

import { KafkaConsumerInterface, createKafkaConsumer } from '~/common/kafka/consumer'
import { instrumentFn } from '~/common/tracing/tracing-utils'
import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'

import { HealthCheckResult, PluginsServerConfig, RawClickHouseEvent } from '../../types'
import {
    DeadLetterRecord,
    ReplayPolicy,
    ReplaySkipReason,
    readDeadLetterRecord,
    readReplayPolicy,
    replayTargetIds,
    shouldReplay,
} from '../services/dead-letter/replay-policy'
import { HogFlowInvocationPipeline } from '../services/hog-flow-invocation-pipeline.service'
import { HogFunctionInvocationPipeline } from '../services/hog-function-invocation-pipeline.service'
import { JobQueue } from '../services/job-queue/job-queue.interface'
import { HogFunctionInvocationGlobals, HogFunctionTypeType } from '../types'
import { convertToHogFunctionInvocationGlobals } from '../utils'
import { CdpConsumerBase, CdpConsumerBaseDeps } from './cdp-base.consumer'

const counterReplayMessages = new Counter({
    name: 'cdp_dlq_replay_messages_total',
    help: 'A dead-letter record was considered by a replay run',
    labelNames: ['outcome'],
})

/**
 * Backstop for a partition that never delivers its last record, so a run cannot hang forever.
 *
 * Polls time out after 500ms, so this is roughly 30 seconds of nothing arriving. It has to clear
 * the time a fresh consumer group spends joining and being assigned, because those polls come back
 * empty too, and ending the run on them would finish before reading anything.
 */
const EMPTY_POLLS_BEFORE_STOP = 60

export interface CdpDlqReplayCounts {
    replayed: number
    queued: number
    skipped: Record<string, number>
    /** Dry-run tally: how many deliveries a real run would produce, keyed `teamId|sourceId|step`. */
    byTarget: Record<string, number>
}

/**
 * Rebuilds invocations for events parked on a dead-letter topic.
 *
 * The run is deliberately bounded. An operator scales it to one replica after the bug that parked
 * the records is fixed and deployed; it reads to the end of the topic and exits. Something watching
 * the topic continuously would push events back at code that has not been fixed yet, and each round
 * trip spends a record's two replays.
 *
 * Two rules the rest of this class exists to keep:
 *
 * It never produces to the source topic. ClickHouse consumes `clickhouse_events_json`, so putting
 * an event back there would duplicate it in the events table. The worker rebuilds invocations and
 * queues those instead, which is also why the generic DLQ replay tooling does not fit here.
 *
 * It rebuilds only the functions a record names. An event that failed for one function out of five
 * already reached the other four, and rebuilding all five would deliver to them twice.
 */
export class CdpDlqReplayConsumer extends CdpConsumerBase<PluginsServerConfig> {
    protected name = 'CdpDlqReplayConsumer'
    protected hogTypes: HogFunctionTypeType[] = ['destination']

    private kafkaConsumer: KafkaConsumerInterface
    private hogFunctionPipeline: HogFunctionInvocationPipeline
    private hogFlowPipeline: HogFlowInvocationPipeline
    private emptyPolls = 0
    private endOffsetsRecorded = false
    /** High watermark per partition, read once at start. The run ends when it reaches all of them. */
    private endOffsets = new Map<number, number>()
    private drained = new Set<number>()

    public readonly counts: CdpDlqReplayCounts = { replayed: 0, queued: 0, skipped: {}, byTarget: {} }

    constructor(
        config: PluginsServerConfig,
        deps: CdpConsumerBaseDeps,
        private jobQueues: { hogQueue: JobQueue; hogflowQueue: JobQueue },
        private policy: ReplayPolicy = readReplayPolicy(config),
        private dryRun: boolean = config.CDP_DLQ_REPLAY_DRY_RUN
    ) {
        super(config, deps)

        // Its own group per run, so a replay never moves the source consumer's offsets, and a later
        // run with a different policy reads the same records again from the beginning.
        // The consumer defaults to `auto.offset.reset: earliest`, which is what a fresh group needs:
        // the run starts at the oldest record still inside the topic's retention.
        this.kafkaConsumer = createKafkaConsumer({
            groupId: `cdp-dlq-replay-${config.CDP_DLQ_REPLAY_RUN_ID}`,
            topic: config.CDP_DLQ_REPLAY_TOPIC,
            callEachBatchWhenEmpty: true,
        })

        this.hogFunctionPipeline = new HogFunctionInvocationPipeline(config, {
            hogFunctionManager: this.hogFunctionManager,
            hogInputsService: this.hogInputsService,
            hogWatcher: this.hogWatcher,
            hogWatcherMirror: this.hogWatcherMirror,
            hogMasker: this.hogMasker,
            hogFunctionMonitoringService: this.hogFunctionMonitoringService,
            cdpUsageReporter: this.cdpUsageReporter,
            quotaLimiting: deps.quotaLimiting,
            redis: this.redis,
            valkeyShadow: this.valkeyShadow,
            // No dead-letter service: a record that fails to rebuild again is left on the topic
            // with its offsets uncommitted rather than parked a second time.
        })
        this.hogFlowPipeline = new HogFlowInvocationPipeline(config, {
            hogFlowManager: this.hogFlowManager,
            hogFlowExecutor: this.hogFlowExecutor,
            hogWatcher: this.hogWatcher,
            hogWatcherMirror: this.hogWatcherMirror,
            hogMasker: this.hogMasker,
            hogFunctionMonitoringService: this.hogFunctionMonitoringService,
            quotaLimiting: deps.quotaLimiting,
            redis: this.redis,
            valkeyShadow: this.valkeyShadow,
        })
    }

    private countSkip(reason: ReplaySkipReason): void {
        this.counts.skipped[reason] = (this.counts.skipped[reason] ?? 0) + 1
        counterReplayMessages.labels({ outcome: `skipped_${reason}` }).inc()
    }

    /**
     * Selects the records this run wants, reading headers only.
     *
     * Skipping before the payload is parsed is what lets a narrow policy scan a topic holding
     * millions of records without paying to deserialize the ones it does not want.
     */
    public selectRecords(messages: Message[], now: number): { message: Message; record: DeadLetterRecord }[] {
        const selected: { message: Message; record: DeadLetterRecord }[] = []
        for (const message of messages) {
            const record = readDeadLetterRecord(message)
            const verdict = shouldReplay(record, this.policy, now)
            if (!verdict.replay) {
                this.countSkip(verdict.skipReason)
                continue
            }
            selected.push({ message, record: record! })
        }
        return selected
    }

    public async replayBatch(messages: Message[], now: number): Promise<void> {
        const selected = this.selectRecords(messages, now)
        if (!selected.length) {
            return
        }

        // Which sources each event may rebuild, keyed by event UUID. `null` means every source of
        // the team, which is right only when nothing was built the first time.
        const targetsByEvent = new Map<string, Set<string> | null>()
        const globalsList: HogFunctionInvocationGlobals[] = []

        for (const { message, record } of selected) {
            const globals = await this.toGlobals(message)
            if (!globals) {
                this.countSkip('unreadable')
                continue
            }
            targetsByEvent.set(globals.event.uuid, replayTargetIds(record, this.policy))
            globalsList.push(globals)
            this.counts.replayed += 1
            this.countTarget(record)
        }

        if (!globalsList.length) {
            return
        }

        if (this.dryRun) {
            counterReplayMessages.labels({ outcome: 'dry_run' }).inc(globalsList.length)
            return
        }

        await this.groupsManager.addGroupsToGlobalsList(globalsList)

        const allows = (id: string, globals: HogFunctionInvocationGlobals): boolean => {
            const targets = targetsByEvent.get(globals.event.uuid)
            return targets === null || targets === undefined ? targets === null : targets.has(id)
        }

        const [hogInvocations, hogflowInvocations] = await Promise.all([
            this.hogFunctionPipeline.buildInvocations(globalsList, {
                hogTypes: this.hogTypes,
                filterFn: (fn) => (fn.filters?.source ?? 'events') === 'events',
                invocationFilterFn: (fn, globals) => allows(fn.id, globals),
            }),
            this.hogFlowPipeline.buildInvocations(globalsList, {
                eligibilityFn: (flow, globals) => flow.trigger.type === 'event' && allows(flow.id, globals),
            }),
        ])

        for (const invocation of [...hogInvocations, ...hogflowInvocations]) {
            // Marks the invocation as recovered so a `replayed` app metric can be added later
            // without changing the queue payload format.
            invocation.queueMetadata = { ...(invocation.queueMetadata as object), replayed_from_dlq: true }
            this.invocationResultsService.invocationResultsRowsService.queueLifecycleRow(invocation, 'running')
        }

        this.counts.queued += hogInvocations.length + hogflowInvocations.length
        counterReplayMessages.labels({ outcome: 'queued' }).inc(hogInvocations.length + hogflowInvocations.length)

        await Promise.all([
            this.jobQueues.hogQueue.queueInvocations(hogInvocations),
            this.jobQueues.hogflowQueue.queueInvocations(hogflowInvocations),
            this.hogFunctionMonitoringService.flush(),
            this.invocationResultsService.invocationResultsRowsService.flush(),
        ])
    }

    private countTarget(record: DeadLetterRecord): void {
        const sources = [...record.hogFunctionIds, ...record.hogFlowIds]
        const keys = sources.length ? sources : ['*']
        for (const source of keys) {
            const key = `${record.teamId ?? 'unknown'}|${source}|${record.step}`
            this.counts.byTarget[key] = (this.counts.byTarget[key] ?? 0) + 1
        }
    }

    /** Rebuilds the globals from the parked bytes, the same conversion the source consumer runs. */
    private async toGlobals(message: Message): Promise<HogFunctionInvocationGlobals | null> {
        try {
            const event = parseJSON(message.value!.toString()) as RawClickHouseEvent
            const team = await this.deps.teamManager.getTeam(event.team_id)
            if (!team) {
                return null
            }
            return convertToHogFunctionInvocationGlobals(event, team, this.config.SITE_URL)
        } catch (error) {
            if (error?.isRetriable === true) {
                throw error
            }
            logger.error('[CdpDlqReplayConsumer] Could not rebuild globals from a parked record', { error })
            return null
        }
    }

    /**
     * Records where the topic ends before reading any of it.
     *
     * This is what bounds the run. A record this run re-parks lands past the recorded end, so one
     * run can never read its own output, and a run started against a topic that is still filling
     * stops at the backlog it was scaled up for rather than following the stream.
     */
    private async recordEndOffsets(): Promise<void> {
        const topic = this.config.CDP_DLQ_REPLAY_TOPIC
        const partitions = await this.kafkaConsumer.getPartitionsForTopic(topic)
        for (const partition of partitions) {
            const [low, high] = await this.kafkaConsumer.queryWatermarkOffsets(topic, partition.id)
            if (high > low) {
                this.endOffsets.set(partition.id, high)
            }
        }
        this.endOffsetsRecorded = true
        logger.info('☠️', 'cdp_dlq_replay_end_offsets', {
            topic,
            partitionsWithRecords: this.endOffsets.size,
        })
    }

    private trackProgress(messages: Message[]): void {
        for (const message of messages) {
            const end = this.endOffsets.get(message.partition)
            if (end !== undefined && message.offset >= end - 1) {
                this.drained.add(message.partition)
            }
        }
    }

    private finish(): void {
        logger.info('☠️', 'cdp_dlq_replay_complete', this.counts)
        void this.stop()
    }

    public override async start(): Promise<void> {
        await super.start()
        await Promise.all([this.jobQueues.hogQueue.startAsProducer(), this.jobQueues.hogflowQueue.startAsProducer()])

        logger.info('☠️', 'cdp_dlq_replay_start', {
            topic: this.config.CDP_DLQ_REPLAY_TOPIC,
            runId: this.config.CDP_DLQ_REPLAY_RUN_ID,
            dryRun: this.dryRun,
            policy: this.policy,
        })

        await this.kafkaConsumer.connect(async (messages) => {
            // Reading broker metadata needs a connected consumer, so the end offsets are recorded on
            // the first poll rather than before connecting.
            if (!this.endOffsetsRecorded) {
                await this.recordEndOffsets()
                if (!this.endOffsets.size) {
                    this.finish()
                    return
                }
            }

            if (!messages.length) {
                if (++this.emptyPolls >= EMPTY_POLLS_BEFORE_STOP) {
                    this.finish()
                }
                return
            }
            this.emptyPolls = 0
            this.trackProgress(messages)
            await instrumentFn('cdpDlqReplay.handleEachBatch', () => this.replayBatch(messages, Date.now()))
            logger.info('☠️', 'cdp_dlq_replay_progress', {
                replayed: this.counts.replayed,
                queued: this.counts.queued,
                skipped: this.counts.skipped,
            })
            if (this.drained.size >= this.endOffsets.size) {
                this.finish()
            }
        })
    }

    public override async stop(): Promise<void> {
        await this.kafkaConsumer.disconnect()
        await Promise.all([this.jobQueues.hogQueue.stopProducer(), this.jobQueues.hogflowQueue.stopProducer()])
        await super.stop()
    }

    public isHealthy(): HealthCheckResult {
        return this.kafkaConsumer.isHealthy()
    }
}

// `Number('')` is 0 and `Number.isFinite(0)` is true, so an unset env var has to be dropped before
// the conversion. Otherwise an empty allow list reads as "team 0 only" and filters out everything.
