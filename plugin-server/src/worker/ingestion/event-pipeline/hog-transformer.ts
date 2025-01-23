import { PluginEvent } from '@posthog/plugin-scaffold'
import { runInstrumentedFunction } from '../../../main/utils'
import { HogExecutor } from '../../../cdp/hog-executor'
import { HogFunctionManager } from '../../../cdp/hog-function-manager'
import { HogFunctionInvocation, HogFunctionType } from '../../../cdp/types'
import { Hub } from '../../../types'
import { status } from '../../../utils/status'
import { UUIDT } from '../../../utils/utils'

export class HogTransformer {
    private hogExecutor: HogExecutor
    private hogFunctionManager: HogFunctionManager
    private hub: Hub

    constructor(hub: Hub) {
        this.hub = hub
        this.hogFunctionManager = new HogFunctionManager(hub)
        this.hogExecutor = new HogExecutor(hub, this.hogFunctionManager)
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

    private createInvocation(event: PluginEvent, hogFunction: HogFunctionType): HogFunctionInvocation {
        return {
            id: new UUIDT().toString(),
            teamId: event.team_id,
            hogFunction,
            globals: {
                project: {
                    name: 'WHERE TO GET THIS FROM??',
                    id: event.team_id,
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
            },
            priority: 0,
            queue: 'hog',
            timings: [],
            functionToExecute: ['transformEvent', []], // No need to pass event as arg since it's in globals
        }
    }

    public async transformEvent(event: PluginEvent): Promise<PluginEvent> {
        return runInstrumentedFunction({
            statsKey: `hogTransformer`,
            func: async () => {
                if (!event.team_id) {
                    return event
                }

                const teamFunctions = await this.hogFunctionManager.getTeamHogFunctions(event.team_id)
                const transformationFunctions = this.getTransformationFunctions()

                // For now, execute each transformation function in sequence
                // Later we can add support for chaining/ordering
                for (const hogFunction of teamFunctions) {
                    const invocation = this.createInvocation(event, hogFunction)
                    const result = this.hogExecutor.execute(invocation, { functions: transformationFunctions })

                    if (result.error) {
                        status.warn('⚠️', 'Error in transformation', { 
                            error: result.error,
                            function_id: hogFunction.id,
                            team_id: event.team_id 
                        })
                        continue
                    }

                    // Type check execResult before accessing result
                    if (!result.execResult) {
                        status.warn('⚠️', 'Missing execution result')
                        continue
                    }
                    const transformedEvent = result.execResult.result as unknown
              

                    // Carefully merge the transformed event properties
                    event = {
                        ...event,
                        properties: {
                            ...event.properties,
                            ...transformedEvent.properties,
                        }
                    }
                }

                return event
            }
        })
    }
} 