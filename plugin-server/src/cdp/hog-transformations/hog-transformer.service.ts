import { PluginEvent } from '@posthog/plugin-scaffold'
import { Counter, Histogram } from 'prom-client'

import { HogFunctionInvocationGlobals, HogFunctionInvocationResult, HogFunctionType } from '../../cdp/types'
import { createInvocation, isLegacyPluginHogFunction } from '../../cdp/utils'
import { runInstrumentedFunction } from '../../main/utils'
import { Hub } from '../../types'
import { logger } from '../../utils/logger'
import { CdpRedis, createCdpRedisPool } from '../redis'
import { buildGlobalsWithInputs, HogExecutorService } from '../services/hog-executor.service'
import { HogFunctionManagerService } from '../services/hog-function-manager.service'
import { HogFunctionMonitoringService } from '../services/hog-function-monitoring.service'
import { HogWatcherService, HogWatcherState } from '../services/hog-watcher.service'
import { LegacyPluginExecutorService } from '../services/legacy-plugin-executor.service'
import { convertToHogFunctionFilterGlobal } from '../utils'
import { checkHogFunctionFilters } from '../utils/hog-function-filtering'
import { cleanNullValues } from './transformation-functions'

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

export const hogTransformationDisabled = new Counter({
    name: 'hog_transformation_disabled_total',
    help: 'Number of times a transformation was skipped due to being disabled',
    labelNames: ['team_id', 'function_id', 'state'],
})

export const hogWatcherLatency = new Histogram({
    name: 'hog_watcher_latency_seconds',
    help: 'Time spent in HogWatcher operations in seconds during ingestion',
    labelNames: ['operation'],
})

export interface TransformationResultPure {
    event: PluginEvent | null
    invocationResults: HogFunctionInvocationResult[]
    watcherPromises: Promise<void>[]
}

export interface TransformationResult extends TransformationResultPure {
    messagePromises: Promise<void>[]
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

    constructor(hub: Hub) {
        this.hub = hub
        this.redis = createCdpRedisPool(hub)
        this.hogFunctionManager = new HogFunctionManagerService(hub)
        this.hogExecutor = new HogExecutorService(hub)
        this.pluginExecutor = new LegacyPluginExecutorService(hub)
        this.hogFunctionMonitoringService = new HogFunctionMonitoringService(hub)
        this.hogWatcher = new HogWatcherService(hub, this.redis)
    }

    public async start(): Promise<void> {
        await this.hogFunctionManager.start()
    }

    public async stop(): Promise<void> {
        await this.hogFunctionManager.stop()
        await this.redis.useClient({ name: 'cleanup' }, async (client) => {
            await client.quit()
        })
    }

    private async getTransformationFunctions() {
        const geoipLookup = await this.hub.geoipService.get()
        return {
            geoipLookup: (val: unknown): any => {
                return typeof val === 'string' ? geoipLookup.city(val) : null
            },
            cleanNullValues,
        }
    }

    private createInvocationGlobals(event: PluginEvent): HogFunctionInvocationGlobals {
        return {
            project: {
                id: event.team_id,
                name: 'WHERE TO GET THIS FROM??',
                url: this.hub.SITE_URL ?? 'http://localhost:8000',
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
        return runInstrumentedFunction({
            statsKey: `hogTransformer.transformEventAndProduceMessages`,
            func: async () => {
                hogTransformationAttempts.inc({ type: 'with_messages' })

                const teamHogFunctions = await this.hogFunctionManager.getHogFunctionsForTeam(event.team_id, [
                    'transformation',
                ])

                const transformationResult = await this.transformEvent(event, teamHogFunctions)
                await this.hogFunctionMonitoringService.processInvocationResults(transformationResult.invocationResults)

                hogTransformationCompleted.inc({ type: 'with_messages' })
                return {
                    ...transformationResult,
                    messagePromises: [this.hogFunctionMonitoringService.produceQueuedMessages()],
                }
            },
        })
    }

    public transformEvent(event: PluginEvent, teamHogFunctions: HogFunctionType[]): Promise<TransformationResultPure> {
        return runInstrumentedFunction({
            statsKey: `hogTransformer.transformEvent`,
            func: async () => {
                hogTransformationInvocations.inc()
                const results: HogFunctionInvocationResult[] = []
                const transformationsSucceeded: string[] = event.properties?.$transformations_succeeded || []
                const transformationsFailed: string[] = event.properties?.$transformations_failed || []
                const transformationsSkipped: string[] = event.properties?.$transformations_skipped || []

                const shouldRunHogWatcher = Math.random() < this.hub.CDP_HOG_WATCHER_SAMPLE_RATE

                for (const hogFunction of teamHogFunctions) {
                    const transformationIdentifier = `${hogFunction.name} (${hogFunction.id})`

                    if (shouldRunHogWatcher) {
                        // Check if function is in a degraded state
                        let functionState = this.getHogFunctionState(hogFunction.id)
                        if (!functionState) {
                            functionState = await this.handleCacheMiss(hogFunction.id)
                        }

                        // If the function is in a degraded state, skip it
                        // If no state is found, we will continue with the transformation
                        if (functionState && functionState >= HogWatcherState.disabledForPeriod) {
                            hogTransformationDisabled
                                .labels({
                                    team_id: hogFunction.team_id.toString(),
                                    function_id: hogFunction.id,
                                    state: HogWatcherState[functionState],
                                })
                                .inc()
                            // For now we continue with the transformation, but in the future this will be a skip
                        }
                    }

                    // Check if we should apply this transformation based on its filters
                    if (this.hub.FILTER_TRANSFORMATIONS_ENABLED_TEAMS.includes(event.team_id)) {
                        const globals = this.createInvocationGlobals(event)
                        const filterGlobals = convertToHogFunctionFilterGlobal(globals)

                        // Check if function has filters - if not, always apply
                        if (hogFunction.filters?.bytecode) {
                            const filterResults = checkHogFunctionFilters({
                                hogFunction,
                                filterGlobals,
                                eventUuid: globals.event?.uuid,
                            })

                            // If filter didn't pass and there was no error, skip this transformation
                            if (!filterResults.match && !filterResults.error) {
                                transformationsSkipped.push(transformationIdentifier)
                                results.push({
                                    invocation: createInvocation(
                                        {
                                            ...globals,
                                            inputs: {}, // Not needed as this is only for a valid return type
                                        },
                                        hogFunction
                                    ),
                                    metrics: filterResults.metrics,
                                    logs: filterResults.logs,
                                    error: null,
                                    finished: true,
                                })
                                continue
                            }
                        }
                    }
                    const result = await this.executeHogFunction(hogFunction, this.createInvocationGlobals(event))

                    results.push(result)

                    if (result.error) {
                        logger.error('⚠️', 'Error in transformation', {
                            error: result.error,
                            function_id: hogFunction.id,
                            team_id: event.team_id,
                        })
                        transformationsFailed.push(transformationIdentifier)
                        continue
                    }

                    if (!result.execResult) {
                        logger.warn('⚠️', 'Execution result is null - dropping event')
                        hogTransformationDroppedEvents.inc()
                        transformationsFailed.push(transformationIdentifier)
                        return {
                            event: null,
                            invocationResults: results,
                            watcherPromises: [],
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

                // Observe the results to update degraded state of HogFunctions
                const watcherPromises: Promise<void>[] = []
                if (shouldRunHogWatcher) {
                    const timer = hogWatcherLatency.startTimer({ operation: 'observeResults' })
                    const watcherPromise = this.hogWatcher
                        .observeResults(results)
                        .then(() => {
                            timer() // Stop the timer when the promise resolves
                        })
                        .catch((error) => {
                            timer() // Make sure to stop the timer even if there's an error
                            logger.warn('⚠️', 'HogWatcher observeResults failed', { error })
                        })
                    watcherPromises.push(watcherPromise)
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
                    watcherPromises,
                }
            },
        })
    }

    private async executeHogFunction(
        hogFunction: HogFunctionType,
        globals: HogFunctionInvocationGlobals
    ): Promise<HogFunctionInvocationResult> {
        const transformationFunctions = await this.getTransformationFunctions()
        const globalsWithInputs = buildGlobalsWithInputs(globals, {
            ...(hogFunction.inputs ?? {}),
            ...(hogFunction.encrypted_inputs ?? {}),
        })

        const invocation = createInvocation(globalsWithInputs, hogFunction)

        const result = isLegacyPluginHogFunction(hogFunction)
            ? await this.pluginExecutor.execute(invocation)
            : this.hogExecutor.execute(invocation, { functions: transformationFunctions })
        return result
    }

    private async handleCacheMiss(hogFunctionId: string): Promise<HogWatcherState | null> {
        logger.error('⚠️', 'HogFunction state cache miss - this should not happen', { hogFunctionId })
        const timer = hogWatcherLatency.startTimer({ operation: 'getStates' })
        const states = await this.hogWatcher.getStates([hogFunctionId])
        timer()

        if (states[hogFunctionId]) {
            this.cachedStates[hogFunctionId] = states[hogFunctionId].state
            return states[hogFunctionId].state
        }
        return null
    }

    public async saveHogFunctionStates(functionIds: string[]): Promise<void> {
        const timer = hogWatcherLatency.startTimer({ operation: 'getStates' })
        const states = await this.hogWatcher.getStates(functionIds)
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

    private getHogFunctionState(hogFunctionId: string): HogWatcherState | null {
        return this.cachedStates[hogFunctionId] || null
    }
}
