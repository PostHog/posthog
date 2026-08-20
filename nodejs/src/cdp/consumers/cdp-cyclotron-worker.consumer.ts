import { instrumented } from '~/common/tracing/tracing-utils'
import { logger } from '~/common/utils/logger'
import { captureException } from '~/common/utils/posthog'

import { HealthCheckResult, PluginsServerConfig } from '../../types'
import { JobQueue } from '../services/job-queue/job-queue.interface'
import {
    CYCLOTRON_INVOCATION_JOB_QUEUES,
    CyclotronJobInvocation,
    CyclotronJobInvocationHogFunction,
    CyclotronJobInvocationResult,
    CyclotronJobQueueKind,
} from '../types'
import { isLegacyPluginHogFunction, isNativeHogFunction, isSegmentPluginHogFunction } from '../utils'
import { dualWrite } from '../utils/dual-store'
import { CdpConsumerBase, CdpConsumerBaseDeps } from './cdp-base.consumer'

/**
 * CDP worker that consumes and processes hog function / hogflow jobs.
 * Receives its job queue backend via constructor injection.
 */
export class CdpCyclotronWorker<
    TConfig extends PluginsServerConfig = PluginsServerConfig,
> extends CdpConsumerBase<TConfig> {
    protected name = 'CdpCyclotronWorker'
    protected cyclotronJobQueue: JobQueue
    protected queue: CyclotronJobQueueKind

    constructor(config: TConfig, deps: CdpConsumerBaseDeps, jobQueue: JobQueue, queue?: CyclotronJobQueueKind) {
        super(config, deps)
        this.queue = queue ?? config.CDP_CYCLOTRON_JOB_QUEUE_CONSUMER_KIND

        if (!CYCLOTRON_INVOCATION_JOB_QUEUES.includes(this.queue)) {
            throw new Error(`Invalid cyclotron job queue kind: ${this.queue}`)
        }

        this.cyclotronJobQueue = jobQueue
    }

    @instrumented({ key: 'cdpConsumer.handleEachBatch.executeInvocations', timeoutMs: 30_000, sendException: false })
    public async processInvocations(invocations: CyclotronJobInvocation[]): Promise<CyclotronJobInvocationResult[]> {
        const loadedInvocations = await this.loadHogFunctions(invocations)

        return await Promise.all(
            loadedInvocations.map((item) => {
                if (isNativeHogFunction(item.hogFunction)) {
                    return this.nativeDestinationExecutorService.execute(item)
                } else if (isLegacyPluginHogFunction(item.hogFunction)) {
                    return this.pluginDestinationExecutorService.execute(item)
                } else if (isSegmentPluginHogFunction(item.hogFunction)) {
                    return this.segmentDestinationExecutorService.execute(item)
                } else {
                    return this.hogExecutorAsync.executeWithAsyncFunctions(item)
                }
            })
        )
    }

    @instrumented({ key: 'cdpConsumer.handleEachBatch.loadHogFunctions', timeoutMs: 10_000, sendException: false })
    protected async loadHogFunctions(
        invocations: CyclotronJobInvocation[]
    ): Promise<CyclotronJobInvocationHogFunction[]> {
        const loadedInvocations: CyclotronJobInvocationHogFunction[] = []
        const failedInvocations: {
            invocation: CyclotronJobInvocation | CyclotronJobInvocationHogFunction
            errorKind: string
            error: string
        }[] = []

        await Promise.all(
            invocations.map(async (item) => {
                const hogFunction = await this.hogFunctionManager.getHogFunction(item.functionId)
                if (!hogFunction) {
                    logger.error('⚠️', 'Error finding hog function', {
                        id: item.functionId,
                    })

                    failedInvocations.push({
                        invocation: item,
                        errorKind: 'function_not_found',
                        error: 'The function could not be found, so this invocation was skipped.',
                    })

                    return
                }

                if (!hogFunction.enabled || hogFunction.deleted) {
                    logger.info('⚠️', 'Skipping invocation due to hog function being deleted or disabled', {
                        id: item.functionId,
                    })

                    failedInvocations.push({
                        // Attach the loaded function so the terminal 'failed' row serializes the
                        // real invocation globals instead of '{}'. The row wins the
                        // ReplacingMergeTree argMax over the earlier 'running' row, so without
                        // its globals the rerun paginator can't rehydrate the invocation and a
                        // re-run after re-enabling would silently skip. Fall back to the raw item
                        // when state globals are absent (nothing to preserve).
                        invocation: item.state?.globals
                            ? { ...item, state: item.state as CyclotronJobInvocationHogFunction['state'], hogFunction }
                            : item,
                        errorKind: hogFunction.deleted ? 'function_deleted' : 'function_disabled',
                        error: hogFunction.deleted
                            ? 'The function was deleted, so this invocation was skipped.'
                            : 'The function was disabled, so this invocation was skipped.',
                    })

                    return
                }

                const hogFuncState = item.state as CyclotronJobInvocationHogFunction['state']

                // Guard against malformed invocation state (globals present but missing
                // project/event). Without this the unguarded derefs below throw an unhandled
                // rejection that crash-loops the worker on a single poison-pill message,
                // stalling the whole partition. Drop it instead so the batch can make progress.
                if (!hogFuncState.globals?.project || !hogFuncState.globals?.event) {
                    logger.error('⚠️', 'Skipping invocation with malformed globals (missing project or event)', {
                        id: item.functionId,
                    })
                    captureException(new Error('Malformed hog function invocation globals: missing project or event'), {
                        tags: { functionId: item.functionId, teamId: String(item.teamId) },
                    })

                    failedInvocations.push({
                        invocation: item,
                        errorKind: 'malformed_invocation',
                        error: 'The invocation data was malformed, so it was skipped.',
                    })

                    return
                }

                await Promise.all([
                    this.groupsManager.addGroupsToGlobals(hogFuncState.globals),
                    !hogFuncState.globals.person
                        ? this.personsManager
                              .getCyclotronPerson(item.teamId, hogFuncState.globals.event.distinct_id, 'distinct_id')
                              .then((person) => {
                                  // Stub when the lookup misses (cookieless events don't persist to
                                  // posthog_persondistinctid; reruns may race with person deletes).
                                  // Leaving undefined would halt any bytecode dereferencing
                                  // person.properties.* with "Could not execute bytecode".
                                  hogFuncState.globals.person = person ?? {
                                      id: '',
                                      name: '',
                                      url: '',
                                      properties: {},
                                  }
                              })
                        : undefined,
                ])

                loadedInvocations.push({
                    ...item,
                    state: hogFuncState,
                    hogFunction,
                })
            })
        )

        if (failedInvocations.length) {
            // Record the terminal lifecycle row BEFORE dequeuing (same ordering as the
            // janitor's poison-pill recovery). Dropping the job without one leaves the
            // invocation stuck 'running' in the runs UI and permanently un-rerunnable.
            const recorded = await Promise.all(
                failedInvocations.map(({ invocation, errorKind, error }) =>
                    this.invocationResultsService.invocationResultsRowsService.recordTerminalFailureDurably(
                        invocation,
                        { errorKind, error }
                    )
                )
            )
            // Keep any job whose terminal row could not be produced so a later fetch retries
            // it, unless lifecycle recording is disabled (then there is no row to go stale).
            const dequeueable = failedInvocations.filter(
                (_, i) => recorded[i] || !this.config.HOG_INVOCATION_RESULTS_ENABLED
            )
            await this.cyclotronJobQueue.dequeueInvocations(dequeueable.map((x) => x.invocation))
        }

        return loadedInvocations
    }

    public async processBatch(
        invocations: CyclotronJobInvocation[]
    ): Promise<{ backgroundTask: Promise<any>; invocationResults: CyclotronJobInvocationResult[] }> {
        if (!invocations.length) {
            return { backgroundTask: Promise.resolve(), invocationResults: [] }
        }

        logger.info('🔁', `${this.name} - handling batch`, {
            size: invocations.length,
        })

        // Heartbeat until the background task settles — the tail includes
        // queueInvocationResults' terminal DB writes, which is where a slow
        // batch would otherwise blow past stallTimeoutMs and get poisoned.
        const stopHeartbeat = this.startPeriodicHeartbeat(invocations)

        let invocationResults: CyclotronJobInvocationResult[]
        try {
            invocationResults = await this.processInvocations(invocations)
        } catch (e) {
            stopHeartbeat()
            throw e
        }

        // NOTE: We can queue and publish all metrics in the background whilst processing the next batch of invocations
        const backgroundTask = this.runBackgroundTasks(invocationResults).finally(stopHeartbeat)

        return { backgroundTask, invocationResults }
    }

    private startPeriodicHeartbeat(invocations: CyclotronJobInvocation[]): () => void {
        const intervalMs = this.config.CDP_CYCLOTRON_HEARTBEAT_INTERVAL_MS
        if (intervalMs <= 0) {
            return () => {}
        }
        const handle = setInterval(() => {
            void this.cyclotronJobQueue.heartbeatInvocations(invocations).catch((err) => {
                logger.warn('⚠️', `${this.name} - heartbeat tick failed`, { error: String(err) })
            })
        }, intervalMs)
        return () => clearInterval(handle)
    }

    @instrumented({ key: 'cdpConsumer.backgroundTask', timeoutMs: 30_000, sendException: false })
    private async runBackgroundTasks(invocationResults: CyclotronJobInvocationResult[]): Promise<void> {
        await this.queueInvocationResults(invocationResults)

        // After this point we parallelize and any issues are logged rather than thrown
        // as retrying now would end up in duplicate messages
        await Promise.allSettled([this.flushMonitoring(invocationResults), this.observeResults(invocationResults)])
    }

    @instrumented({ key: 'cdpConsumer.backgroundTask.monitoringFlush', timeoutMs: 15_000, sendException: false })
    private async flushMonitoring(invocationResults: CyclotronJobInvocationResult[]): Promise<void> {
        try {
            await this.invocationResultsService.queueInvocationResultsAndFlush(invocationResults)
        } catch (err) {
            captureException(err)
            logger.error('Error processing invocation results', { err })
        }
    }

    @instrumented({ key: 'cdpConsumer.backgroundTask.hogWatcherObserve', timeoutMs: 10_000, sendException: false })
    private async observeResults(invocationResults: CyclotronJobInvocationResult[]): Promise<void> {
        try {
            await dualWrite(
                'hog-watcher.observeResults',
                () => this.hogWatcher.observeResults(invocationResults),
                () => this.hogWatcherMirror.observeResults(invocationResults)
            )
        } catch (err: any) {
            captureException(err)
            logger.error('Error observing results', { err })
        }
    }

    @instrumented({ key: 'cdpConsumer.backgroundTask.queueInvocationResults', timeoutMs: 15_000, sendException: false })
    protected async queueInvocationResults(invocations: CyclotronJobInvocationResult[]) {
        await this.cyclotronJobQueue.queueInvocationResults(invocations)
    }

    public override async start() {
        await super.start()
        await this.cyclotronJobQueue.startAsProducer()
        await this.cyclotronJobQueue.startAsConsumer(this.queue, (batch) => this.processBatch(batch))
    }

    public override async stop() {
        logger.info('🔄', 'Stopping cyclotron worker consumer')
        await this.cyclotronJobQueue.stopConsumer()
        await this.cyclotronJobQueue.stopProducer()

        // IMPORTANT: super always comes last
        await super.stop()
    }

    public isHealthy(): HealthCheckResult {
        return this.cyclotronJobQueue.isHealthy()
    }
}
