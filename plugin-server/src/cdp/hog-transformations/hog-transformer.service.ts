import { PluginEvent } from '@posthog/plugin-scaffold'
import { Counter } from 'prom-client'

import {
    HogFunctionInvocationGlobals,
    HogFunctionInvocationResult,
    HogFunctionType,
    HogFunctionTypeType,
} from '../../cdp/types'
import { createInvocation, isLegacyPluginHogFunction } from '../../cdp/utils'
import { runInstrumentedFunction } from '../../main/utils'
import { Hub } from '../../types'
import { logger } from '../../utils/logger'
import { UUIDT } from '../../utils/utils'
import { execHog } from '../services/hog-executor.service'
import { buildGlobalsWithInputs, HogExecutorService } from '../services/hog-executor.service'
import { HogFunctionManagerService } from '../services/hog-function-manager.service'
import { HogFunctionManagerLazyService } from '../services/hog-function-manager-lazy.service'
import { HogFunctionMonitoringService } from '../services/hog-function-monitoring.service'
import { LegacyPluginExecutorService } from '../services/legacy-plugin-executor.service'
import { convertToHogFunctionFilterGlobal } from '../utils'
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

export interface TransformationResultPure {
    event: PluginEvent | null
    invocationResults: HogFunctionInvocationResult[]
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
    private hogFunctionManagerLazy: HogFunctionManagerLazyService

    constructor(hub: Hub) {
        this.hub = hub
        this.hogFunctionManager = new HogFunctionManagerService(hub)
        this.hogFunctionManagerLazy = new HogFunctionManagerLazyService(hub)
        this.hogExecutor = new HogExecutorService(hub)
        this.pluginExecutor = new LegacyPluginExecutorService(hub)
        this.hogFunctionMonitoringService = new HogFunctionMonitoringService(hub)
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

    public async start(): Promise<void> {
        const hogTypes: HogFunctionTypeType[] = ['transformation']
        await this.hogFunctionManager.start(hogTypes)
    }

    public async stop(): Promise<void> {
        await this.hogFunctionManager.stop()
    }

    public transformEventAndProduceMessages(event: PluginEvent): Promise<TransformationResult> {
        return runInstrumentedFunction({
            statsKey: `hogTransformer.transformEventAndProduceMessages`,
            func: async () => {
                hogTransformationAttempts.inc({ type: 'with_messages' })

                const teamHogFunctions = this.hogFunctionManager.getTeamHogFunctions(event.team_id)
    if (this.hub.CDP_HOG_FUNCTION_LAZY_LOADING_ENABLED) {
                    try {
                        const teamHogFunctionsLazy = await this.hogFunctionManagerLazy.getHogFunctionsForTeam(
                            event.team_id,
                            ['transformation']
                        )
                        if (teamHogFunctionsLazy.length !== teamHogFunctions.length) {
                            logger.warn('loaded different number of functions', {
                                lazy: teamHogFunctionsLazy.length,
                                eager: teamHogFunctions.length,
                            })
                        }
                    } catch (e) {
                        logger.error('Error lazy loading hog functions', { error: e })
                    }
                }            const transformationResult = await this.transformEvent(event, teamHogFunctions)
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

                // For now, execute each transformation function in sequence
                for (const hogFunction of teamHogFunctions) {
                    const transformationIdentifier = `${hogFunction.name} (${hogFunction.id})`

                    // Check if we should apply this transformation based on its filters
                    if (this.hub.FILTER_TRANSFORMATIONS_ENABLED) {
                        const globals = this.createInvocationGlobals(event)
                        const filterGlobals = convertToHogFunctionFilterGlobal(globals)
                        const shouldApplyTransformation = this.checkEventAgainstFilters(hogFunction, filterGlobals)

                        if (!shouldApplyTransformation) {
                            transformationsSkipped.push(transformationIdentifier)
                            results.push({
                                invocation: createInvocation(
                                    {
                                        ...globals,
                                        inputs: {}, // Not needed as this is only for a valid return type
                                    },
                                    hogFunction
                                ),
                                metrics: [
                                    {
                                        team_id: event.team_id,
                                        app_source_id: hogFunction.id,
                                        metric_kind: 'other',
                                        metric_name: 'filtered',
                                        count: 1,
                                    },
                                ],
                                logs: [],
                                error: null,
                                finished: true,
                            })

                            continue
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

                // Only add the properties if there were transformations
                if (
                    transformationsSucceeded.length > 0 ||
                    transformationsFailed.length > 0 ||
                    transformationsSkipped.length > 0
                ) {
                    event.properties = {
                        ...event.properties,
                        $transformations_succeeded: transformationsSucceeded,
                        $transformations_failed: transformationsFailed,
                        $transformations_skipped: transformationsSkipped,
                    }
                }

                return {
                    event,
                    invocationResults: results,
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

    /**
     * Checks if an event matches the filters of a transformation
     */
    private checkEventAgainstFilters(hogFunction: HogFunctionType, filterGlobals: any): boolean {
        // If there are no filters, apply the transformation
        if (!hogFunction.filters?.bytecode) {
            return true
        }

        try {
            // Use execHog directly to evaluate the filters
            const filterResult = execHog(hogFunction.filters.bytecode, {
                globals: filterGlobals,
            })

            // If there was an error evaluating the filters, still apply the transformation
            if (filterResult.error) {
                logger.error('🔍', 'Error evaluating filters for transformation - applying anyway', {
                    error: filterResult.error.message,
                    transformation_id: hogFunction.id,
                    transformation_name: hogFunction.name,
                })
                return true
            }

            // The filter result is a boolean indicating whether to apply the transformation
            return typeof filterResult.result === 'boolean' && filterResult.result
        } catch (error) {
            logger.error('🔍', 'Exception evaluating filters for transformation - applying anyway', {
                error: error.message,
                transformation_id: hogFunction.id,
                transformation_name: hogFunction.name,
            })
            return true
        }
    }
}
