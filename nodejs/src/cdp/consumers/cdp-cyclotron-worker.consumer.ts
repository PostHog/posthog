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
import { mirrorCall } from '../utils/mirror-call'
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
                    return this.hogExecutor.executeWithAsyncFunctions(item)
                }
            })
        )
    }

    @instrumented({ key: 'cdpConsumer.handleEachBatch.loadHogFunctions', timeoutMs: 10_000, sendException: false })
    protected async loadHogFunctions(
        invocations: CyclotronJobInvocation[]
    ): Promise<CyclotronJobInvocationHogFunction[]> {
        const loadedInvocations: CyclotronJobInvocationHogFunction[] = []
        const failedInvocations: CyclotronJobInvocation[] = []

        await Promise.all(
            invocations.map(async (item) => {
                const hogFunction = await this.hogFunctionManager.getHogFunction(item.functionId)
                if (!hogFunction) {
                    logger.error('⚠️', 'Error finding hog function', {
                        id: item.functionId,
                    })

                    failedInvocations.push(item)

                    return
                }

                if (!hogFunction.enabled || hogFunction.deleted) {
                    logger.info('⚠️', 'Skipping invocation due to hog function being deleted or disabled', {
                        id: item.functionId,
                    })

                    failedInvocations.push(item)

                    return
                }

                const hogFuncState = item.state as CyclotronJobInvocationHogFunction['state']

                await Promise.all([
                    this.groupsManager.addGroupsToGlobals(hogFuncState.globals),
                    !hogFuncState.globals.person
                        ? this.personsManager
                              .getCyclotronPerson(item.teamId, hogFuncState.globals.event.distinct_id, 'distinct_id')
                              .then((person) => {
                                  // Fall back to an empty-shaped stub when the lookup misses.
                                  // Happens on the rerun path for cookieless-mode events
                                  // (`cookieless_*` distinct_ids never persist to
                                  // `posthog_persondistinctid`) and for reruns where the
                                  // person has since been deleted. This matches the shape
                                  // the events pipeline attaches at original ingest time
                                  // (`{id: '', name, url}`, no `properties`). Leaving
                                  // `globals.person` as `undefined` would make any input
                                  // bytecode that dereferences `person.properties.*`
                                  // (e.g. the Google Ads template's
                                  // `person.properties.gclid ?? … ?? event.properties.gclid`)
                                  // halt on the first branch with "Could not execute
                                  // bytecode" — never reaching the event-level fallback
                                  // that would otherwise recover the send.
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

        await this.cyclotronJobQueue.dequeueInvocations(failedInvocations)

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

        const invocationResults = await this.processInvocations(invocations)

        // NOTE: We can queue and publish all metrics in the background whilst processing the next batch of invocations
        const backgroundTask = this.runBackgroundTasks(invocationResults)

        return { backgroundTask, invocationResults }
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
            await Promise.all([
                this.hogWatcher.observeResults(invocationResults),
                mirrorCall('hog-watcher.observeResults', () =>
                    this.hogWatcherMirror?.observeResults(invocationResults)
                ),
            ])
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
