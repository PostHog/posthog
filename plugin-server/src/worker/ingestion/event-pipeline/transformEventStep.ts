import { PluginEvent } from '@posthog/plugin-scaffold'
import { runInstrumentedFunction } from 'main/utils'

import { HogExecutor } from '../../../cdp/hog-executor'
import { HogFunctionInvocation, HogFunctionType } from '../../../cdp/types'
import { Hub } from '../../../types'
import { status } from '../../../utils/status'
import { UUIDT } from '../../../utils/utils'


// TODO THIS IS THE PLAN :) 

// what we need to give the transformEventStep:
// 1. the event
// 2. hogfunctionmanager (we will have this on the hub)
// 3. HogExecutor ()

// create a class that lives on the hub that then instantiates the HogExecutor, HogfunctionManager
// then in the end we would put that in the hub and end up being hub.HogTransformer.transformEvent(event)

// wihtin the class we would create the invocations, run the transformation and return the event
// encapuslate the 'build in' transformationsFn in the class
// the transformEvent also takes care of 'building' the new returned event with only overrwriting or extending the properties of the event that we want

// write proper tests (unit and integration)

  // TODO we need logs and these things and we do not want them to block the main thread so avoid async if possible
 // TODO logs and metrics should be published to a list of promises and then await the whole promise batch

export async function transformEventStep(hub: Hub, event: PluginEvent): Promise<PluginEvent> {
    // Check if transformations are enabled via env variable
    if (!hub.HOG_TRANSFORMATIONS_ALPHA) {
        return event
    }

    // return hub.HogTransformer.transformEvent(event)

    const transformationFunctions = {
        geoipLookup: (ipAddress: unknown) => {
            if (typeof ipAddress !== 'string') {
                return null
            }
            if (!hub.mmdb) {
                return null
            }
            try {
                return hub.mmdb.city(ipAddress)
            } catch {
                return null
            }
        },
    }

    // TODO e.g. like produceQueuedMessages in cdp-consumers.ts
    return runInstrumentedFunction({
        statsKey: `transformEventStep`,
        func: () => {
            // TODO get it from db (this needs to come from the HogFunctionManager,
            // TODO where the hell do i init this thing this needs to be in the hub)
            const hogFunction: HogFunctionType = {
                id: 'transformation',
                team_id: event.team_id,
                type: 'transformation',
                name: 'Event Transformation',
                enabled: true,
                hog: `
                    function transformEvent(event) {
                        // Add your transformation logic here
                        event.$geoip = geoipLookup(event.ip)
                        return event
                    }
                `,
                bytecode: [], // Empty bytecode as we're using source directly
                inputs_schema: [],
                inputs: {},
                filters: null,
                mappings: null,
                masking: null,
            }

            // TODO
            const invocation: HogFunctionInvocation = {
                id: new UUIDT().toString(),
                teamId: event.team_id,
                hogFunction,
                globals: {
                    project: {
                        id: team.id,
                        name: team.name,
                        url: hub.SITE_URL ?? 'http://localhost:8000',
                    },
                    event: {
                        uuid: event.uuid,
                        event: event.event,
                        distinct_id: event.distinct_id,
                        properties: event.properties || {},
                        elements_chain: event.properties?.elements_chain || '', // todo figure this part out (where to get it from)
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

            // todo move the executor and the hogfunction manager to its own service and then give it to the hub
            const hogExecutor = new HogExecutor(hub, hub.hogFunctionManager)
            const result = hogExecutor.execute(invocation, { functions: transformationFunctions })

            if (result.error) {
                status.warn('⚠️', 'Error in transformation', { error: result.error })
                return event
            }

            status.info('🔄', 'HOG Transformation (Alpha)', {
                event_type: event.event,
                distinct_id: event.distinct_id,
                team_id: event.team_id,
            })

            // TODO dont spread transformedEvent, be explicit about what is being set
            const transformedEvent = result.execResult.result // this is unknown so we need to type check it.
            return {
                ...event,
                ...transformedEvent,
            }
        },
    })
}
