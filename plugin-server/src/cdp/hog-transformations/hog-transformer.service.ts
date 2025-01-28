import { PluginEvent } from '@posthog/plugin-scaffold'

import {
    HogFunctionAppMetric,
    HogFunctionInvocation,
    HogFunctionInvocationGlobalsWithInputs,
    HogFunctionInvocationResult,
    HogFunctionType,
    HogFunctionTypeType,
} from '../../cdp/types'
import { createInvocation, fixLogDeduplication } from '../../cdp/utils'
import { KAFKA_APP_METRICS_2, KAFKA_LOG_ENTRIES } from '../../config/kafka-topics'
import { runInstrumentedFunction } from '../../main/utils'
import { AppMetric2Type, Hub, TimestampFormat } from '../../types'
import { safeClickhouseString } from '../../utils/db/utils'
import { status } from '../../utils/status'
import { castTimestampOrNow } from '../../utils/utils'
import { HogExecutorService } from '../services/hog-executor.service'
import { HogFunctionManagerService } from '../services/hog-function-manager.service'

export interface TransformationResult {
    event: PluginEvent
    messagePromises: Promise<void>[]
}

export class HogTransformerService {
    private hogExecutor: HogExecutorService
    private hogFunctionManager: HogFunctionManagerService
    private hub: Hub

    constructor(hub: Hub) {
        this.hub = hub
        this.hogFunctionManager = new HogFunctionManagerService(hub)
        this.hogExecutor = new HogExecutorService(hub, this.hogFunctionManager)
    }

    private getTransformationFunctions() {
        return {
            geoipLookup: (ipAddress: unknown) => {
                if (typeof ipAddress !== 'string') {
                    return null
                }
                if (!this.hub.mmdb) {
                    return null
                }
                try {
                    return this.hub.mmdb.city(ipAddress)
                } catch {
                    return null
                }
            },
        }
    }

    private createInvocationGlobals(event: PluginEvent): HogFunctionInvocationGlobalsWithInputs {
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
            inputs: {},
        }
    }

    private createHogFunctionInvocation(event: PluginEvent, hogFunction: HogFunctionType): HogFunctionInvocation {
        const globals = this.createInvocationGlobals(event)

        return createInvocation(globals, hogFunction)
    }

    public async start(): Promise<void> {
        const hogTypes: HogFunctionTypeType[] = ['transformation']
        await this.hogFunctionManager.start(hogTypes)
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

    public transformEvent(event: PluginEvent): Promise<TransformationResult> {
        return runInstrumentedFunction({
            statsKey: `hogTransformer`,
            // eslint-disable-next-line @typescript-eslint/require-await
            func: async () => {
                const teamHogFunctions = this.hogFunctionManager.getTeamHogFunctions(event.team_id)
                const transformationFunctions = this.getTransformationFunctions()
                const messagePromises: Promise<void>[] = []

                // For now, execute each transformation function in sequence
                for (const hogFunction of teamHogFunctions) {
                    const invocation = this.createHogFunctionInvocation(event, hogFunction)
                    const result = this.hogExecutor.execute(invocation, { functions: transformationFunctions })

                    // Process results and collect promises
                    messagePromises.push(
                        ...this.processInvocationResult({
                            invocation,
                            logs: result.logs,
                            error: result.error,
                            execResult: result.execResult,
                            finished: true,
                        })
                    )

                    if (result.error) {
                        status.error('⚠️', 'Error in transformation', {
                            error: result.error,
                            function_id: hogFunction.id,
                            team_id: event.team_id,
                        })
                        continue
                    }

                    if (!result.execResult) {
                        status.error('⚠️', 'Missing execution result - no transformation applied')
                        continue
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
                            continue
                        }
                        event.event = transformedEvent.event
                    }
                }

                return {
                    event,
                    messagePromises,
                }
            },
        })
    }
}
