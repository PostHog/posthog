import { Message } from 'node-rdkafka'
import { Counter } from 'prom-client'

import { KafkaConsumerInterface, createKafkaConsumer } from '~/common/kafka/consumer'
import type { RdKafkaConsumerConfig } from '~/common/kafka/consumer/consumer-v1'
import { instrumentFn } from '~/common/tracing/tracing-utils'
import { logger } from '~/common/utils/logger'

import { HealthCheckResult, PluginsServerConfig } from '../../types'
import type { InvocationFailureSink } from '../services/dead-letter/cdp-dead-letter.service'
import {
    DeadLetterRecord,
    SourceKind,
    readDeadLetterRecord,
    readParkedEvent,
    replayTargetIds,
    replayTargetKinds,
} from '../services/dead-letter/replay-policy'
import { HogFlowInvocationPipeline } from '../services/hog-flow-invocation-pipeline.service'
import { HogFunctionInvocationPipeline } from '../services/hog-function-invocation-pipeline.service'
import { JobQueue } from '../services/job-queue/job-queue.interface'
import { HogFunctionInvocationGlobals, HogFunctionTypeType, InvocationBuildFailure } from '../types'
import { convertToHogFunctionInvocationGlobals } from '../utils'
import { CdpConsumerBase, CdpConsumerBaseDeps } from './cdp-base.consumer'

const counterReplayRecords = new Counter({
    name: 'cdp_dlq_replay_records_total',
    help: 'A dead-letter record was read by the replay worker',
    labelNames: ['outcome'],
})

const counterReplayInvocations = new Counter({
    name: 'cdp_dlq_replay_invocations_total',
    help: 'An invocation was rebuilt and queued by the replay worker',
})

/** The group is fixed, so its committed offsets are what stop a record being replayed twice. */
const REPLAY_GROUP_ID = 'cdp-dlq-replay'

/**
 * Catches what the pipelines would otherwise report to a dead-letter topic.
 *
 * A filter or an input that throws is handled per function: the builder returns it here and the
 * pipeline carries on, so a rebuild that fails the same way it did the first time comes back as an
 * empty invocation list and no error. Without this the worker would commit past a record whose
 * delivery never happened. Collecting them lets the batch fail instead.
 *
 * `recordProcessFailure` answers false, which is what a pipeline with no sink at all would see, so
 * an unexpected error keeps failing the batch where it is thrown.
 */
class ReplayFailureCollector implements InvocationFailureSink {
    public failures: InvocationBuildFailure[] = []

    public recordBuildFailures(_globals: HogFunctionInvocationGlobals, failures: InvocationBuildFailure[]): void {
        this.failures.push(...failures)
    }

    public recordProcessFailure(): boolean {
        return false
    }

    public clear(): void {
        this.failures = []
    }
}

export interface CdpDlqReplayCounts {
    replayed: number
    queued: number
}

/**
 * Rebuilds invocations for events parked on a dead-letter topic.
 *
 * The deployment runs at zero replicas. An operator scales it to one once the bug that parked the
 * records is fixed and deployed, and back to zero to stop it. There is no enabled flag: the worker
 * always drains while it is running, so there is no state where it holds a Kafka client it is not
 * using and no health check that has to explain one.
 *
 * Three rules the rest of this class exists to keep:
 *
 * It never produces to the source topic. ClickHouse consumes `clickhouse_events_json`, so putting
 * an event back there would duplicate it in the events table. The worker rebuilds invocations and
 * queues those instead, which is also why the generic DLQ replay tooling does not fit here.
 *
 * It rebuilds only the functions a record names. An event that failed for one function out of five
 * already reached the other four, and rebuilding all five would deliver to them twice.
 *
 * It commits offsets only once every invocation in the batch is queued. Anything else leaves them
 * where they are and fails the batch, so a record that cannot be replayed blocks rather than being
 * skipped. Scaling it back to zero is how an operator unblocks it and fixes forward. Batch size is
 * the deployment's `CONSUMER_BATCH_SIZE`: nothing here depends on it, but it decides how much of a
 * batch waits behind one record that will not replay.
 */
export class CdpDlqReplayConsumer extends CdpConsumerBase<PluginsServerConfig> {
    protected name = 'CdpDlqReplayConsumer'
    protected hogTypes: HogFunctionTypeType[] = ['destination']

    private kafkaConsumer: KafkaConsumerInterface
    private hogFunctionPipeline: HogFunctionInvocationPipeline
    private hogFlowPipeline: HogFlowInvocationPipeline
    private buildFailures = new ReplayFailureCollector()

    public readonly counts: CdpDlqReplayCounts = { replayed: 0, queued: 0 }

    constructor(
        config: PluginsServerConfig,
        deps: CdpConsumerBaseDeps,
        private jobQueues: { hogQueue: JobQueue; hogflowQueue: JobQueue }
    ) {
        super(config, deps)

        // Offsets are left to the consumer, which stores them once the batch handler resolves. That
        // is the guarantee this worker needs: the handler awaits the rebuild and the queueing, so a
        // record is only committed after its invocations exist, and a throw anywhere leaves the
        // offset where it was.
        //
        // `auto.offset.reset` is set rather than inherited, because KAFKA_CONSUMER_AUTO_OFFSET_RESET
        // applies to every consumer in the deployment. This one runs at zero replicas, so records
        // always land before it connects: a `latest` value would skip the backlog it was scaled up
        // to drain and report a clean run having replayed nothing.
        this.kafkaConsumer = createKafkaConsumer({ groupId: REPLAY_GROUP_ID, topic: config.CDP_DLQ_REPLAY_TOPIC }, {
            'auto.offset.reset': 'earliest',
        } as RdKafkaConsumerConfig)

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
            deadLetterService: this.buildFailures,
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
            deadLetterService: this.buildFailures,
        })
    }

    /**
     * Rebuilds one batch and queues the invocations.
     *
     * Everything here either succeeds for every record in the batch or throws. A record that cannot
     * be rebuilt — bytes that will not parse, a team that no longer exists — throws like any other
     * failure, so the offset stays put and the worker blocks on it. An operator turns the worker
     * off and either fixes forward or moves the group's offset past that record by hand.
     */
    public async replayBatch(messages: Message[]): Promise<void> {
        this.buildFailures.clear()
        const selected: { message: Message; record: DeadLetterRecord }[] = []
        for (const message of messages) {
            const record = readDeadLetterRecord(message)
            if (!record) {
                throw new Error(
                    `Dead-letter record at ${message.topic}:${message.partition}:${message.offset} has no ` +
                        'dlq_step header, so there is nothing to rebuild from it'
                )
            }
            selected.push({ message, record })
        }
        if (!selected.length) {
            return
        }

        // Which sources each event may rebuild, held against the globals object the rebuild runs
        // from. One event can be parked more than once, because a record is written per event and
        // step: once at `filter` for one function, once at `inputs` for another. Their targets are
        // merged and the event is rebuilt once.
        //
        // Team and event UUID only group the candidates, and the parked bytes decide. A UUID comes
        // from the client, so one team can send two different events under the same one, and
        // merging those would hand a destination parked for one of them the other's payload. A
        // record parks the source bytes untouched, so two records for the same event compare equal.
        const eventKey = (globals: HogFunctionInvocationGlobals): string =>
            `${globals.project.id}:${globals.event.uuid}`
        const parkedByKey = new Map<string, { globals: HogFunctionInvocationGlobals; value: Buffer }[]>()
        const targetsByEvent = new Map<HogFunctionInvocationGlobals, Set<string> | null>()
        const kindsByEvent = new Map<HogFunctionInvocationGlobals, Set<SourceKind> | null>()
        const globalsList: HogFunctionInvocationGlobals[] = []

        const resolved = await Promise.all(selected.map(({ message }) => this.toGlobals(message)))

        for (const [index, { message, record }] of selected.entries()) {
            const globals = resolved[index]
            if (!globals) {
                throw new Error(
                    `Could not rebuild an event from ${message.topic}:${message.partition}:${message.offset} — ` +
                        'refusing to commit past a parked event that was never replayed'
                )
            }
            const targets = replayTargetIds(record)
            const kinds = replayTargetKinds(record)
            // Present for every selected record: readDeadLetterRecord refuses one with no payload.
            const value = message.value!
            const key = eventKey(globals)
            const candidates = parkedByKey.get(key) ?? []
            const sameEvent = candidates.find((parked) => parked.value.equals(value))?.globals
            if (sameEvent) {
                const existingTargets = targetsByEvent.get(sameEvent)!
                const existingKinds = kindsByEvent.get(sameEvent)!
                // `null` is "everything", so a union with anything stays `null`.
                targetsByEvent.set(
                    sameEvent,
                    existingTargets === null || targets === null ? null : new Set([...existingTargets, ...targets])
                )
                kindsByEvent.set(
                    sameEvent,
                    existingKinds === null || kinds === null ? null : new Set([...existingKinds, ...kinds])
                )
            } else {
                candidates.push({ globals, value })
                parkedByKey.set(key, candidates)
                targetsByEvent.set(globals, targets)
                kindsByEvent.set(globals, kinds)
                globalsList.push(globals)
            }
            this.counts.replayed += 1
        }

        await this.groupsManager.addGroupsToGlobalsList(globalsList)

        // Both pipelines hand the predicates back the globals object they were given, so the lookup
        // is by identity rather than by any value read off the event.
        const allows = (id: string, globals: HogFunctionInvocationGlobals): boolean => {
            const targets = targetsByEvent.get(globals)
            return targets === null || targets === undefined ? targets === null : targets.has(id)
        }

        // A record that names a kind but no id is a pipeline that threw while the other one queued
        // its invocations. Rebuilding the kind it does not name would deliver those a second time.
        const allowsKind = (kind: SourceKind, globals: HogFunctionInvocationGlobals): boolean => {
            const kinds = kindsByEvent.get(globals)
            return kinds === null || kinds === undefined ? kinds === null : kinds.has(kind)
        }

        const [hogInvocations, hogflowInvocations] = await Promise.all([
            this.hogFunctionPipeline.buildInvocations(globalsList, {
                hogTypes: this.hogTypes,
                filterFn: (fn) => (fn.filters?.source ?? 'events') === 'events',
                invocationFilterFn: (fn, globals) => allowsKind('hog_function', globals) && allows(fn.id, globals),
            }),
            this.hogFlowPipeline.buildInvocations(globalsList, {
                eligibilityFn: (flow, globals) =>
                    flow.trigger.type === 'event' && allowsKind('hog_flow', globals) && allows(flow.id, globals),
            }),
        ])

        // A filter or an input that throws does not reject the build, so an empty invocation list is
        // how a still-broken destination looks from here. Zero invocations on its own is not enough
        // to go on: a deleted, disabled, quota-limited or masked destination is also correctly
        // built and correctly not delivered.
        if (this.buildFailures.failures.length) {
            const [first] = this.buildFailures.failures
            throw new Error(
                `${this.buildFailures.failures.length} source(s) in this batch still fail to build, ` +
                    `first ${first.sourceKind} ${first.sourceId} at ${first.step}: ${first.error}. ` +
                    'Refusing to commit past records whose delivery did not happen'
            )
        }

        for (const invocation of [...hogInvocations, ...hogflowInvocations]) {
            // Marks the invocation as recovered so a `replayed` app metric can be added later
            // without changing the queue payload format.
            invocation.queueMetadata = { ...(invocation.queueMetadata as object), replayed_from_dlq: true }
            this.invocationResultsService.invocationResultsRowsService.queueLifecycleRow(invocation, 'running')
        }

        this.counts.queued += hogInvocations.length + hogflowInvocations.length
        // Records and invocations are different things: one record can rebuild several invocations
        // or none. Counting invocations under a record-shaped label made every outcome rate wrong.
        counterReplayRecords.labels({ outcome: 'rebuilt' }).inc(globalsList.length)
        counterReplayInvocations.inc(hogInvocations.length + hogflowInvocations.length)

        await Promise.all([
            this.jobQueues.hogQueue.queueInvocations(hogInvocations),
            this.jobQueues.hogflowQueue.queueInvocations(hogflowInvocations),
            this.hogFunctionMonitoringService.flush(),
            this.invocationResultsService.invocationResultsRowsService.flush(),
        ])
    }

    /**
     * Rebuilds the globals from the parked bytes, resolving everything around the event fresh.
     *
     * The event body is replayed exactly as it arrived, but everything the pipeline reads around it
     * is read again now: the team, the groups, and the person. `convertToHogFunctionInvocationGlobals`
     * would otherwise hand the destination the person snapshot frozen into the event at capture,
     * which can be months stale by the time a replay runs, while groups were already being resolved
     * fresh. A destination receiving a delivery today should see today's person.
     *
     * Errors are not caught. The caller turns a null into a thrown batch, and anything thrown here
     * reaches the same place, because the worker blocks on a record it cannot replay rather than
     * committing past it.
     */
    private async toGlobals(message: Message): Promise<HogFunctionInvocationGlobals | null> {
        const event = readParkedEvent(message)
        if (!event) {
            return null
        }
        const team = await this.deps.teamManager.getTeam(event.team_id)
        if (!team) {
            return null
        }
        const globals = convertToHogFunctionInvocationGlobals(event, team, this.config.SITE_URL)
        const person = await this.personsManager.getCyclotronPerson(event.team_id, event.distinct_id, 'distinct_id', {
            forceFresh: true,
        })
        // Keep the frozen snapshot when the person cannot be resolved: deleted, merged away, or
        // never written. Sending the destination nothing would be a bigger change than sending
        // it what the event carried.
        return person ? { ...globals, person } : globals
    }

    public override async start(): Promise<void> {
        await super.start()
        await Promise.all([this.jobQueues.hogQueue.startAsProducer(), this.jobQueues.hogflowQueue.startAsProducer()])

        logger.info('☠️', 'cdp_dlq_replay_start', { topic: this.config.CDP_DLQ_REPLAY_TOPIC })

        await this.kafkaConsumer.connect(async (messages) => {
            if (!messages.length) {
                return
            }

            await instrumentFn('cdpDlqReplay.handleEachBatch', () => this.replayBatch(messages))

            logger.info('☠️', 'cdp_dlq_replay_progress', this.counts)
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
