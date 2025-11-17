import { Counter, Gauge, Histogram } from 'prom-client'

import { PluginEvent } from '@posthog/plugin-scaffold'

import { instrumentFn } from '~/common/tracing/tracing-utils'

import { CyclotronJobInvocationResult, HogFunctionInvocationGlobals, HogFunctionType } from '../../cdp/types'
import { isLegacyPluginHogFunction } from '../../cdp/utils'
import { Hub } from '../../types'
import { logger } from '../../utils/logger'
import { CdpRedis, createCdpRedisPool } from '../redis'
import { HogExecutorService } from '../services/hog-executor.service'
import { LegacyPluginExecutorService } from '../services/legacy-plugin-executor.service'
import { HogFunctionManagerService } from '../services/managers/hog-function-manager.service'
import { HogFunctionMonitoringService } from '../services/monitoring/hog-function-monitoring.service'
import { HogWatcherService, HogWatcherState } from '../services/monitoring/hog-watcher.service'
import { convertToHogFunctionFilterGlobal, filterFunctionInstrumented } from '../utils/hog-function-filtering'
import { createInvocation } from '../utils/invocation-utils'
import { getTransformationFunctions } from './transformation-functions'

export const hogTransformationDroppedEvents = new Counter({
    name: 'hog_transformation_dropped_events',
    help: 'Indicates how many events are dropped by hog transformations',
})

export const hogTransformationInvocations = new Counter({
    name: 'hog_transformation_invocations_total',
    help: 'Number of times transformEvent was called directly',
})

export const hogTransformationAttempts = new Counter({
    name: 'hog_transformation_attempts_total',
    help: 'Number of transformation attempts before any processing',
    labelNames: ['type'],
})

export const hogTransformationCompleted = new Counter({
    name: 'hog_transformation_completed_total',
    help: 'Number of successfully completed transformations',
    labelNames: ['type'],
})

export const hogWatcherLatency = new Histogram({
    name: 'hog_watcher_latency_seconds',
    help: 'Time spent in HogWatcher operations in seconds during ingestion',
    labelNames: ['operation'],
})

export const hogTransformationPendingInvocationResults = new Gauge({
    name: 'hog_transformation_pending_invocation_results',
    help: 'Number of invocation results accumulated and waiting to be processed. High values indicate memory accumulation.',
})

export interface TransformationResult {
    event: PluginEvent | null
    invocationResults: CyclotronJobInvocationResult[]
}

export class HogTransformerService {
    private hogExecutor: HogExecutorService
    private hogFunctionManager: HogFunctionManagerService
    private hub: Hub
    private pluginExecutor: LegacyPluginExecutorService
    private hogFunctionMonitoringService: HogFunctionMonitoringService
    private hogWatcher: HogWatcherService
    private redis: CdpRedis
    private cachedStates: Record<string, HogWatcherState> = {}
    private invocationResults: CyclotronJobInvocationResult[] = []

    constructor(hub: Hub) {
        this.hub = hub
        this.redis = createCdpRedisPool(hub)
        this.hogFunctionManager = new HogFunctionManagerService(hub)
        this.hogExecutor = new HogExecutorService(hub)
        this.pluginExecutor = new LegacyPluginExecutorService(hub)
        this.hogFunctionMonitoringService = new HogFunctionMonitoringService(hub)
        this.hogWatcher = new HogWatcherService(hub, this.redis)
    }

    public async start(): Promise<void> {}

    public async stop(): Promise<void> {
        await this.processInvocationResults()
        await this.redis.useClient({ name: 'cleanup' }, async (client) => {
            await client.quit()
        })
    }

    public async processInvocationResults(): Promise<void> {
        const results = [...this.invocationResults]
        this.invocationResults = []
        hogTransformationPendingInvocationResults.set(0)

        const shouldRunHogWatcher = Math.random() < this.hub.CDP_HOG_WATCHER_SAMPLE_RATE

        await Promise.allSettled([
            this.hogFunctionMonitoringService
                .queueInvocationResults(results)
                .then(() => this.hogFunctionMonitoringService.flush()),

            shouldRunHogWatcher
                ? this.hogWatcher.observeResults(results).catch((error) => {
                      logger.warn('⚠️', 'HogWatcher observeResults failed', { error })
                  })
                : Promise.resolve(),
        ])
    }

    private async getTransformationFunctions() {
        const geoipLookup = await this.hub.geoipService.get()
        return getTransformationFunctions(geoipLookup)
    }

    private createInvocationGlobals(event: PluginEvent): HogFunctionInvocationGlobals {
        return {
            project: {
                id: event.team_id,
                name: '',
                url: this.hub.SITE_URL,
            },
            event: {
                uuid: event.uuid,
                event: event.event,
                distinct_id: event.distinct_id,
                properties: event.properties || {},
                elements_chain: event.properties?.elements_chain || '',
                timestamp: event.timestamp || '',
                url: event.properties?.$current_url || '',
            },
        }
    }

    public transformEventAndProduceMessages(event: PluginEvent): Promise<TransformationResult> {
        return instrumentFn(`hogTransformer.transformEventAndProduceMessages`, async () => {
            hogTransformationAttempts.inc({ type: 'with_messages' })

            const teamHogFunctions = await this.hogFunctionManager.getHogFunctionsForTeam(event.team_id, [
                'transformation',
            ])

            const transformationResult = await this.transformEvent(event, teamHogFunctions)

            for (const result of transformationResult.invocationResults) {
                this.invocationResults.push(result)
            }
            hogTransformationPendingInvocationResults.set(this.invocationResults.length)

            hogTransformationCompleted.inc({ type: 'with_messages' })
            return {
                ...transformationResult,
            }
        })
    }

    public transformEvent(event: PluginEvent, teamHogFunctions: HogFunctionType[]): Promise<TransformationResult> {
        // Sanitize transform event properties
        if (event.properties) {
            for (const key of ['$transformations_failed', '$transformations_skipped', '$transformations_succeeded']) {
                if (key in event.properties) {
                    delete event.properties[key]
                }
            }
        }

        return instrumentFn(`hogTransformer.transformEvent`, async () => {
            hogTransformationInvocations.inc()
            const results: CyclotronJobInvocationResult[] = []
            const transformationsSucceeded: string[] = []
            const transformationsFailed: string[] = []
            const transformationsSkipped: string[] = []

            const shouldRunHogWatcher = Math.random() < this.hub.CDP_HOG_WATCHER_SAMPLE_RATE

            for (const hogFunction of teamHogFunctions) {
                const transformationIdentifier = `${hogFunction.name} (${hogFunction.id})`

                // Check if function is in a degraded state, but only if hogwatcher is enabled
                if (shouldRunHogWatcher) {
                    const functionState = this.cachedStates[hogFunction.id]

                    // If the function is in a degraded state, skip it
                    if (functionState && functionState === HogWatcherState.disabled) {
                        this.hogFunctionMonitoringService.queueAppMetric(
                            {
                                team_id: event.team_id,
                                app_source_id: hogFunction.id,
                                metric_kind: 'failure',
                                metric_name: 'disabled_permanently',
                                count: 1,
                            },
                            'hog_function'
                        )
                        continue
                    }
                }

                const globals = this.createInvocationGlobals(event)
                const filterGlobals = convertToHogFunctionFilterGlobal(globals)

                // Check if function has filters - if not, always apply
                if (hogFunction.filters?.bytecode) {
                    const filterResults = await filterFunctionInstrumented({
                        fn: hogFunction,
                        filters: hogFunction.filters,
                        filterGlobals,
                    })

                    // If filter didn't pass skip the actual transformation and add logs and errors from the filterResult
                    this.hogFunctionMonitoringService.queueAppMetrics(filterResults.metrics, 'hog_function')
                    this.hogFunctionMonitoringService.queueLogs(filterResults.logs, 'hog_function')

                    if (!filterResults.match) {
                        transformationsSkipped.push(transformationIdentifier)
                        continue
                    }
                }

                const result = await this.executeHogFunction(hogFunction, this.createInvocationGlobals(event))

                results.push(result)

                if (result.error) {
                    transformationsFailed.push(transformationIdentifier)
                    continue
                }

                if (!result.execResult) {
                    hogTransformationDroppedEvents.inc()
                    this.hogFunctionMonitoringService.queueAppMetric(
                        {
                            team_id: event.team_id,
                            app_source_id: hogFunction.id,
                            metric_kind: 'other',
                            metric_name: 'dropped',
                            count: 1,
                        },
                        'hog_function'
                    )
                    transformationsFailed.push(transformationIdentifier)
                    return {
                        event: null,
                        invocationResults: results,
                    }
                }

                const transformedEvent: unknown = result.execResult

                if (
                    !transformedEvent ||
                    typeof transformedEvent !== 'object' ||
                    !('properties' in transformedEvent) ||
                    !transformedEvent.properties ||
                    typeof transformedEvent.properties !== 'object'
                ) {
                    logger.error('⚠️', 'Invalid transformation result - missing or invalid properties', {
                        function_id: hogFunction.id,
                    })
                    transformationsFailed.push(transformationIdentifier)
                    continue
                }

                event.properties = {
                    ...transformedEvent.properties,
                }

                event.ip = event.properties.$ip ?? null

                if ('event' in transformedEvent) {
                    if (typeof transformedEvent.event !== 'string') {
                        logger.error('⚠️', 'Invalid transformation result - event name must be a string', {
                            function_id: hogFunction.id,
                            event: transformedEvent.event,
                        })
                        transformationsFailed.push(transformationIdentifier)
                        continue
                    }
                    event.event = transformedEvent.event
                }

                if ('distinct_id' in transformedEvent) {
                    if (typeof transformedEvent.distinct_id !== 'string') {
                        logger.error('⚠️', 'Invalid transformation result - distinct_id must be a string', {
                            function_id: hogFunction.id,
                            distinct_id: transformedEvent.distinct_id,
                        })
                        transformationsFailed.push(transformationIdentifier)
                        continue
                    }
                    event.distinct_id = transformedEvent.distinct_id
                }

                transformationsSucceeded.push(transformationIdentifier)
            }

            if (transformationsFailed.length > 0) {
                event.properties = {
                    ...event.properties,
                    $transformations_failed: transformationsFailed,
                }
            }

            if (transformationsSkipped.length > 0) {
                event.properties = {
                    ...event.properties,
                    $transformations_skipped: transformationsSkipped,
                }
            }

            if (transformationsSucceeded.length > 0) {
                event.properties = {
                    ...event.properties,
                    $transformations_succeeded: transformationsSucceeded,
                }
            }

            return {
                event,
                invocationResults: results,
            }
        })
    }

    private async executeHogFunction(
        hogFunction: HogFunctionType,
        globals: HogFunctionInvocationGlobals
    ): Promise<CyclotronJobInvocationResult> {
        const transformationFunctions = await this.getTransformationFunctions()
        const globalsWithInputs = await this.hogExecutor.buildInputsWithGlobals(hogFunction, globals)

        const invocation = createInvocation(globalsWithInputs, hogFunction)

        const result = isLegacyPluginHogFunction(hogFunction)
            ? await this.pluginExecutor.execute(invocation)
            : await this.hogExecutor.execute(invocation, {
                  functions: transformationFunctions,
                  asyncFunctionsNames: [],
              })
        return result
    }

    public async fetchAndCacheHogFunctionStates(functionIds: string[]): Promise<void> {
        const timer = hogWatcherLatency.startTimer({ operation: 'getStates' })
        const states = await this.hogWatcher.getEffectiveStates(functionIds)
        timer()

        // Save only the state enum value to cache
        Object.entries(states).forEach(([id, state]) => {
            this.cachedStates[id] = state.state
        })
    }

    public clearHogFunctionStates(functionIds?: string[]): void {
        if (functionIds) {
            // Clear specific function states
            functionIds.forEach((id) => {
                delete this.cachedStates[id]
            })
        } else {
            // Clear all states if no IDs provided
            this.cachedStates = {}
        }
    }
}
