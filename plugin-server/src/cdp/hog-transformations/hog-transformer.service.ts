import { PluginEvent } from '@posthog/plugin-scaffold'
import { Counter } from 'prom-client'

import {
    HogFunctionAppMetric,
    HogFunctionInvocationGlobals,
    HogFunctionInvocationResult,
    HogFunctionType,
    HogFunctionTypeType,
} from '../../cdp/types'
import { CDP_TEST_ID, createInvocation, fixLogDeduplication, isLegacyPluginHogFunction } from '../../cdp/utils'
import { KAFKA_APP_METRICS_2, KAFKA_LOG_ENTRIES } from '../../config/kafka-topics'
import { runInstrumentedFunction } from '../../main/utils'
import { AppMetric2Type, Hub, TimestampFormat } from '../../types'
import { safeClickhouseString } from '../../utils/db/utils'
import { status } from '../../utils/status'
import { castTimestampOrNow } from '../../utils/utils'
import { buildGlobalsWithInputs, HogExecutorService } from '../services/hog-executor.service'
import { HogFunctionManagerService } from '../services/hog-function-manager.service'
import { LegacyPluginExecutorService } from '../services/legacy-plugin-executor.service'
import { cleanNullValues, createGeoipLookup } from './transformation-functions'

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

    constructor(hub: Hub) {
        this.hub = hub
        this.hogFunctionManager = new HogFunctionManagerService(hub)
        this.hogExecutor = new HogExecutorService(hub, this.hogFunctionManager)
        this.pluginExecutor = new LegacyPluginExecutorService(hub)
    }

    private getTransformationFunctions() {
        return {
            geoipLookup: createGeoipLookup(this.hub.mmdb),
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

    private produceAppMetric(metric: HogFunctionAppMetric): Promise<void> {
        const appMetric: AppMetric2Type = {
            app_source: 'hog_function',
            ...metric,
            timestamp: castTimestampOrNow(null, TimestampFormat.ClickHouse),
        }

        return this.hub.kafkaProducer
            .queueMessages([
                {
                    topic: KAFKA_APP_METRICS_2,
                    messages: [
                        {
                            value: safeClickhouseString(JSON.stringify(appMetric)),
                            key: appMetric.app_source_id,
                        },
                    ],
                },
            ])
            .catch((error) => {
                status.error('⚠️', `failed to produce app metric: ${error}`)
            })
    }

    private produceLogs(result: HogFunctionInvocationResult): Promise<void> {
        const logs = fixLogDeduplication(
            result.logs.map((logEntry) => ({
                ...logEntry,
                team_id: result.invocation.hogFunction.team_id,
                log_source: 'hog_function',
                log_source_id: result.invocation.hogFunction.id,
                instance_id: result.invocation.id,
            }))
        )

        return this.hub.kafkaProducer
            .queueMessages(
                logs.map((logEntry) => ({
                    topic: KAFKA_LOG_ENTRIES,
                    messages: [
                        {
                            value: safeClickhouseString(JSON.stringify(logEntry)),
                            key: logEntry.instance_id,
                        },
                    ],
                }))
            )
            .catch((error) => {
                status.error('⚠️', `failed to produce logs: ${error}`)
            })
    }

    private processInvocationResult(result: HogFunctionInvocationResult): Promise<void>[] {
        const promises: Promise<void>[] = []

        if (result.finished || result.error) {
            promises.push(
                this.produceAppMetric({
                    team_id: result.invocation.teamId,
                    app_source_id: result.invocation.hogFunction.id,
                    metric_kind: result.error ? 'failure' : 'success',
                    metric_name: result.error ? 'failed' : 'succeeded',
                    count: 1,
                })
            )
        }

        if (result.logs.length > 0) {
            promises.push(this.produceLogs(result))
            // Clear the logs after processing
            result.logs = []
        }

        return promises
    }

    public transformEventAndProduceMessages(
        event: PluginEvent,
        runTestFunctions: boolean = false
    ): Promise<TransformationResult> {
        return runInstrumentedFunction({
            statsKey: `hogTransformer.transformEventAndProduceMessages`,
            func: async () => {
                hogTransformationAttempts.inc({ type: 'with_messages' })
                const transformationResult = await this.transformEvent(event, runTestFunctions)
                const messagePromises: Promise<void>[] = []

                transformationResult.invocationResults.forEach((result) => {
                    messagePromises.push(...this.processInvocationResult(result))
                })

                hogTransformationCompleted.inc({ type: 'with_messages' })
                return {
                    ...transformationResult,
                    messagePromises,
                }
            },
        })
    }

    public transformEvent(event: PluginEvent, runTestFunctions: boolean = false): Promise<TransformationResultPure> {
        return runInstrumentedFunction({
            statsKey: `hogTransformer.transformEvent`,

            func: async () => {
                hogTransformationInvocations.inc()
                const teamHogFunctions = this.hogFunctionManager.getTeamHogFunctions(event.team_id)
                const results: HogFunctionInvocationResult[] = []
                const transformationsSucceeded: string[] = event.properties?.$transformations_succeeded || []
                const transformationsFailed: string[] = event.properties?.$transformations_failed || []

                // For now, execute each transformation function in sequence
                for (const hogFunction of teamHogFunctions) {
                    if (hogFunction.name.includes(CDP_TEST_ID) && !runTestFunctions) {
                        // Skip test functions if we're not running in test mode
                        continue
                    }
                    const transformationIdentifier = `${hogFunction.name} (${hogFunction.id})`
                    const result = await this.executeHogFunction(hogFunction, this.createInvocationGlobals(event))

                    results.push(result)

                    if (result.error) {
                        status.error('⚠️', 'Error in transformation', {
                            error: result.error,
                            function_id: hogFunction.id,
                            team_id: event.team_id,
                        })
                        transformationsFailed.push(transformationIdentifier)
                        continue
                    }

                    if (!result.execResult) {
                        status.warn('⚠️', 'Execution result is null - dropping event')
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
                        status.error('⚠️', 'Invalid transformation result - missing or invalid properties', {
                            function_id: hogFunction.id,
                        })
                        transformationsFailed.push(transformationIdentifier)
                        continue
                    }

                    event.properties = {
                        ...event.properties,
                        ...transformedEvent.properties,
                    }

                    if ('event' in transformedEvent) {
                        if (typeof transformedEvent.event !== 'string') {
                            status.error('⚠️', 'Invalid transformation result - event name must be a string', {
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
                            status.error('⚠️', 'Invalid transformation result - distinct_id must be a string', {
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
                if (transformationsSucceeded.length > 0 || transformationsFailed.length > 0) {
                    event.properties = {
                        ...event.properties,
                        $transformations_succeeded: transformationsSucceeded,
                        $transformations_failed: transformationsFailed,
                    }
                }

                return {
                    event,
                    invocationResults: results,
                }
            },
        })
    }

    public async executeHogFunction(
        hogFunction: HogFunctionType,
        globals: HogFunctionInvocationGlobals
    ): Promise<HogFunctionInvocationResult> {
        const transformationFunctions = this.getTransformationFunctions()
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
}
