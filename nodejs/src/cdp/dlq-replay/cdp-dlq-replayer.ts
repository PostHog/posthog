import { NativeConnection, Worker } from '@temporalio/worker'
import { Message } from 'node-rdkafka'
import { Counter } from 'prom-client'

import { buildTemporalDataConverter, buildTemporalTLSConfig } from '~/common/temporal/connection'
import { logger } from '~/common/utils/logger'

import {
    HealthCheckResult,
    HealthCheckResultError,
    HealthCheckResultOk,
    PluginsServerConfig,
    RawClickHouseEvent,
} from '../../types'
import { CdpConsumerBase, CdpConsumerBaseDeps } from '../consumers/cdp-base.consumer'
import type { InvocationFailureSink } from '../services/dead-letter/cdp-dead-letter.service'
import {
    DeadLetterRecord,
    SourceKind,
    partitionReplayFailures,
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
import { createReplayActivities } from './activities'
import { DlqPartitionReader } from './partition-reader'

const counterReplayRecords = new Counter({
    name: 'cdp_dlq_replay_records_total',
    help: 'A dead-letter record was read by the replay worker',
    labelNames: ['outcome'],
})

const counterReplayInvocations = new Counter({
    name: 'cdp_dlq_replay_invocations_total',
    help: 'An invocation was rebuilt and queued by the replay worker',
})

/**
 * A record this version cannot replay: unreadable bytes, a team that no longer exists, or a source
 * that still fails to build for a reason that is ours. Thrown before anything is queued, so the
 * caller can retry the same records one at a time without delivering any of them twice.
 */
export class UnreplayableRecordsError extends Error {
    constructor(message: string) {
        super(message)
        this.name = 'UnreplayableRecordsError'
    }
}

export interface ReplayBatchResult {
    rebuilt: number
    queued: number
}

/**
 * Catches what the pipelines would otherwise report to a dead-letter topic.
 *
 * A filter or an input that throws is handled per function: the builder returns it here and the
 * pipeline carries on, so a rebuild that fails the same way it did the first time comes back as an
 * empty invocation list and no error. Without this the worker would move past a record whose
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

const position = (message: Message): string => `${message.topic}:${message.partition}:${message.offset}`

function tryReadParkedEvent(message: Message): RawClickHouseEvent | null {
    try {
        return readParkedEvent(message)
    } catch {
        return null
    }
}

/**
 * Rebuilds invocations for events parked on the dead-letter topic, and serves the Temporal
 * activities that drive it.
 *
 * A replay is a `cdp-dlq-replay` workflow that an operator starts once the bug that parked the
 * records is fixed and deployed. The workflow runs on the Python workers and calls the activities
 * here on their own task queue, because the rebuild needs the same pipelines the events consumer
 * runs. Between runs the worker only polls an idle queue.
 *
 * Two rules the rest of this class exists to keep:
 *
 * It never produces to the source topic. ClickHouse consumes `clickhouse_events_json`, so putting
 * an event back there would duplicate it in the events table. The worker rebuilds invocations and
 * queues those instead, which is also why the generic DLQ replay workflow does not fit here.
 *
 * It rebuilds only the functions a record names. An event that failed for one function out of five
 * already reached the other four, and rebuilding all five would deliver to them twice.
 */
export class CdpDlqReplayer extends CdpConsumerBase<PluginsServerConfig> {
    protected name = 'CdpDlqReplayer'
    protected hogTypes: HogFunctionTypeType[] = ['destination']

    private hogFunctionPipeline: HogFunctionInvocationPipeline
    private hogFlowPipeline: HogFlowInvocationPipeline
    private buildFailures = new ReplayFailureCollector()
    private worker?: Worker
    private workerRun?: Promise<void>

    constructor(
        config: PluginsServerConfig,
        deps: CdpConsumerBaseDeps,
        private jobQueues: { hogQueue: JobQueue; hogflowQueue: JobQueue }
    ) {
        super(config, deps)

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
     * Everything here either succeeds for every record in the batch or throws. A record this
     * version cannot replay throws `UnreplayableRecordsError` before anything is queued. Any other
     * throw can come after some invocations were queued, so a caller must not retry the batch
     * record by record on it.
     */
    public async replayBatch(messages: Message[]): Promise<ReplayBatchResult> {
        this.buildFailures.clear()
        const selected: { message: Message; record: DeadLetterRecord; event: RawClickHouseEvent }[] = []
        for (const message of messages) {
            const record = readDeadLetterRecord(message)
            if (!record) {
                throw new UnreplayableRecordsError(
                    `Dead-letter record at ${position(message)} has no dlq_step header, so there is nothing to rebuild from it`
                )
            }
            const event = tryReadParkedEvent(message)
            if (!event) {
                throw new UnreplayableRecordsError(`Could not read an event from ${position(message)}`)
            }
            selected.push({ message, record, event })
        }
        if (!selected.length) {
            return { rebuilt: 0, queued: 0 }
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

        const resolved = await Promise.all(selected.map(({ event }) => this.toGlobals(event)))

        for (const [index, { message, record }] of selected.entries()) {
            const globals = resolved[index]
            if (!globals) {
                throw new UnreplayableRecordsError(
                    `The team of the event at ${position(message)} no longer exists, so it has nowhere to replay to`
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
        const { blocking, unreplayable } = partitionReplayFailures(this.buildFailures.failures)
        if (unreplayable) {
            counterReplayRecords.labels({ outcome: 'unreplayable' }).inc(unreplayable)
        }
        if (blocking.length) {
            const [first] = blocking
            throw new UnreplayableRecordsError(
                `${blocking.length} source(s) in this batch still fail to build, ` +
                    `first ${first.sourceKind} ${first.sourceId} at ${first.step}: ${first.error}. ` +
                    'Refusing to move past records whose delivery did not happen'
            )
        }

        for (const invocation of [...hogInvocations, ...hogflowInvocations]) {
            // Marks the invocation as recovered so a `replayed` app metric can be added later
            // without changing the queue payload format.
            invocation.queueMetadata = { ...(invocation.queueMetadata as object), replayed_from_dlq: true }
            this.invocationResultsService.invocationResultsRowsService.queueLifecycleRow(invocation, 'running')
        }

        const queued = hogInvocations.length + hogflowInvocations.length
        // Records and invocations are different things: one record can rebuild several invocations
        // or none. Counting invocations under a record-shaped label made every outcome rate wrong.
        counterReplayRecords.labels({ outcome: 'rebuilt' }).inc(globalsList.length)
        counterReplayInvocations.inc(queued)

        await Promise.all([
            this.jobQueues.hogQueue.queueInvocations(hogInvocations),
            this.jobQueues.hogflowQueue.queueInvocations(hogflowInvocations),
            this.hogFunctionMonitoringService.flush(),
            this.invocationResultsService.invocationResultsRowsService.flush(),
        ])

        return { rebuilt: selected.length, queued }
    }

    /**
     * Rebuilds the globals from the parked event, resolving everything around it fresh.
     *
     * The event body is replayed exactly as it arrived, but everything the pipeline reads around it
     * is read again now: the team, the groups, and the person. `convertToHogFunctionInvocationGlobals`
     * would otherwise hand the destination the person snapshot frozen into the event at capture,
     * which can be months stale by the time a replay runs, while groups were already being resolved
     * fresh. A destination receiving a delivery today should see today's person.
     */
    private async toGlobals(event: RawClickHouseEvent): Promise<HogFunctionInvocationGlobals | null> {
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

        const address = `${this.config.TEMPORAL_HOST}:${this.config.TEMPORAL_PORT || '7233'}`
        const connection = await NativeConnection.connect({ address, tls: await buildTemporalTLSConfig(this.config) })
        this.worker = await Worker.create({
            connection,
            namespace: this.config.TEMPORAL_NAMESPACE || 'default',
            taskQueue: this.config.CDP_DLQ_REPLAY_TASK_QUEUE,
            activities: createReplayActivities({
                replayer: this,
                openReader: () => DlqPartitionReader.open(),
                topic: this.config.CDP_EVENTS_DLQ_TOPIC,
            }),
            dataConverter: buildTemporalDataConverter(this.config),
            // One partition at a time per pod. Two activities rebuilding at once would share the
            // failure collector, and a replay is never in a hurry.
            maxConcurrentActivityTaskExecutions: 1,
        })
        this.workerRun = this.worker.run().catch((error) => {
            logger.error('☠️', 'cdp_dlq_replay_worker_failed', { error: String(error) })
        })

        logger.info('☠️', 'cdp_dlq_replay_start', { address, taskQueue: this.config.CDP_DLQ_REPLAY_TASK_QUEUE })
    }

    public override async stop(): Promise<void> {
        // Shutdown lets a running activity finish and commit its batch, so a retry on another pod
        // starts after it instead of sending it again.
        this.worker?.shutdown()
        await this.workerRun
        await Promise.all([this.jobQueues.hogQueue.stopProducer(), this.jobQueues.hogflowQueue.stopProducer()])
        await super.stop()
    }

    public isHealthy(): HealthCheckResult {
        const state = this.worker?.getState()
        return state === 'RUNNING'
            ? new HealthCheckResultOk()
            : new HealthCheckResultError('Temporal worker is not running', { state })
    }
}
