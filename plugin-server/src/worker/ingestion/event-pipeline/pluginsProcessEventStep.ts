import { PluginEvent } from '@posthog/plugin-scaffold'

import { runInstrumentedFunction } from '../../../main/utils'
import { runProcessEvent } from '../../plugins/run'
import { droppedEventCounter } from './metrics'
import { EventPipelineRunner } from './runner'

// Some properties are internal, which plugins shouldn't be able to change
// We don't want these to be passed to the processEvent plugins
const hiddenProperties = [
    '$heatmap_data', // Is processed and removed at a later pipeline step
    '$elements', // This is deprecated
    '$groups', // To avoid dependencies if we want to change how we use this property
    '$active_feature_flags', // To avoid dependencies if we want to change how we use this property
]

export async function pluginsProcessEventStep(
    runner: EventPipelineRunner,
    event: PluginEvent
): Promise<PluginEvent | null> {
    const limitedEvent = {
        ...event,
        properties: {
            ...Object.fromEntries(
                Object.entries(event.properties || {}).filter(([key]) => !hiddenProperties.includes(key))
            ),
        },
    }
    const processedEvent = await runInstrumentedFunction({
        timeoutContext: () => ({
            event: JSON.stringify(limitedEvent),
        }),
        func: () => runProcessEvent(runner.hub, limitedEvent),
        statsKey: 'kafka_queue.single_event',
        timeoutMessage: 'Still running plugins on event. Timeout warning after 30 sec!',
        teamId: event.team_id,
    })

    if (processedEvent) {
        // re-add hidden properties overwriting any changes made by plugins
        return {
            ...processedEvent,
            properties: {
                ...processedEvent.properties,
                ...Object.fromEntries(
                    Object.entries(event.properties || {}).filter(([key]) => hiddenProperties.includes(key))
                ),
            },
        }
    } else {
        // processEvent might not return an event. This is expected and plugins, e.g. downsample plugin uses it.
        droppedEventCounter.inc()
        return null
    }
}
