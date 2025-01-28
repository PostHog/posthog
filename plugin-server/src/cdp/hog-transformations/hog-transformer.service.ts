import { PluginEvent } from '@posthog/plugin-scaffold'

import {
    HogFunctionInvocation,
    HogFunctionInvocationGlobalsWithInputs,
    HogFunctionInvocationResult,
    HogFunctionType,
    HogFunctionTypeType,
} from '../../cdp/types'
import { createInvocation } from '../../cdp/utils'
import { runInstrumentedFunction } from '../../main/utils'
import { Hub } from '../../types'
import { status } from '../../utils/status'
import { HogExecutorService } from '../services/hog-executor.service'
import { HogFunctionManagerService } from '../services/hog-function-manager.service'

export interface TransformationResult {
    event: PluginEvent
    invocationResults: HogFunctionInvocationResult[]
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

    public async transformEvent(event: PluginEvent): Promise<TransformationResult> {
        return runInstrumentedFunction({
            statsKey: `hogTransformer`,
            // eslint-disable-next-line @typescript-eslint/require-await
            func: async () => {
                const teamHogFunctions = this.hogFunctionManager.getTeamHogFunctions(event.team_id)
                const transformationFunctions = this.getTransformationFunctions()
                const invocationResults: HogFunctionInvocationResult[] = []

                // For now, execute each transformation function in sequence
                // Later we can add support for chaining/ordering
                for (const hogFunction of teamHogFunctions) {
                    const invocation = this.createHogFunctionInvocation(event, hogFunction)
                    const result = this.hogExecutor.execute(invocation, { functions: transformationFunctions })

                    // Store the HogFunctionInvocationResult to show logs and metrics in the UI
                    invocationResults.push({
                        invocation,
                        logs: result.logs,
                        error: result.error,
                        execResult: result.execResult,
                        finished: true,
                    })

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
                    invocationResults,
                }
            },
        })
    }
}
