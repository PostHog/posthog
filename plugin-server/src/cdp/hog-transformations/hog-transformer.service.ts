import { PluginEvent } from '@posthog/plugin-scaffold'

import {
    HogFunctionInvocation,
    HogFunctionInvocationGlobals,
    HogFunctionType,
    HogFunctionTypeType,
} from '../../cdp/types'
import { createInvocation, isLegacyPluginHogFunction } from '../../cdp/utils'
import { runInstrumentedFunction } from '../../main/utils'
import { Hub } from '../../types'
import { status } from '../../utils/status'
import { buildGlobalsWithInputs, HogExecutorService } from '../services/hog-executor.service'
import { HogFunctionManagerService } from '../services/hog-function-manager.service'
import { LegacyPluginExecutorService } from '../services/legacy-plugin-executor.service'

export class HogTransformerService {
    private hogExecutor: HogExecutorService
    private hogFunctionManager: HogFunctionManagerService
    private hub: Hub
    private pluginExecutor: LegacyPluginExecutorService

    constructor(hub: Hub) {
        this.hub = hub
        this.hogFunctionManager = new HogFunctionManagerService(hub)
        this.hogExecutor = new HogExecutorService(hub, this.hogFunctionManager)
        this.pluginExecutor = new LegacyPluginExecutorService()
    }

    // Built-in transformation functions that will be available to all transformations
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

    private createHogFunctionInvocation(event: PluginEvent, hogFunction: HogFunctionType): HogFunctionInvocation {
        const globalsWithInputs = buildGlobalsWithInputs(this.createInvocationGlobals(event), {
            ...(hogFunction.inputs ?? {}),
            ...(hogFunction.encrypted_inputs ?? {}),
        })

        return createInvocation(globalsWithInputs, hogFunction)
    }

    public async start(): Promise<void> {
        const hogTypes: HogFunctionTypeType[] = ['transformation']
        await this.hogFunctionManager.start(hogTypes)
    }

    public transformEvent(event: PluginEvent): Promise<PluginEvent | null> {
        return runInstrumentedFunction({
            statsKey: `hogTransformer`,
            // there is no await as all operations are sync

            func: async () => {
                const teamHogFunctions = this.hogFunctionManager.getTeamHogFunctions(event.team_id)
                const transformationFunctions = this.getTransformationFunctions()
                // For now, execute each transformation function in sequence
                // Later we can add support for chaining/ordering
                for (const hogFunction of teamHogFunctions) {
                    const invocation = this.createHogFunctionInvocation(event, hogFunction)

                    const result = isLegacyPluginHogFunction(hogFunction)
                        ? await this.pluginExecutor.execute(invocation)
                        : this.hogExecutor.execute(invocation, { functions: transformationFunctions })

                    if (result.error) {
                        status.warn('⚠️', 'Error in transformation', {
                            error: result.error,
                            function_id: hogFunction.id,
                            team_id: event.team_id,
                        })
                        continue
                    }

                    // Type check execResult before accessing result
                    if (!result.execResult) {
                        // TODO: Correct this - if we have no result but a successful execution then we should be dropping the event
                        status.warn('⚠️', 'Execution result is null - dropping event')
                        return null
                    }

                    const transformedEvent: unknown = result.execResult

                    // Validate the transformed event has a valid properties object
                    if (
                        !transformedEvent ||
                        typeof transformedEvent !== 'object' ||
                        !('properties' in transformedEvent) ||
                        !transformedEvent.properties ||
                        typeof transformedEvent.properties !== 'object'
                    ) {
                        status.warn('⚠️', 'Invalid transformation result - missing or invalid properties', {
                            function_id: hogFunction.id,
                        })
                        continue
                    }

                    event.properties = {
                        ...event.properties,
                        ...transformedEvent.properties,
                    }

                    // Validate event name is a string if present and update it
                    if ('event' in transformedEvent) {
                        if (typeof transformedEvent.event !== 'string') {
                            status.warn('⚠️', 'Invalid transformation result - event name must be a string', {
                                function_id: hogFunction.id,
                                event: transformedEvent.event,
                            })
                            continue
                        }
                        event.event = transformedEvent.event
                    }
                }
                return event
            },
        })
    }
}
