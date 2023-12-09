import { PluginEvent } from '@posthog/plugin-scaffold'

import { runInstrumentedFunction } from '../../../main/utils'
import { runProcessEvent } from '../../plugins/run'
import { droppedEventCounter } from './metrics'
import { EventPipelineRunner } from './runner'

export async function pluginsProcessEventStep(
    runner: EventPipelineRunner,
    event: PluginEvent
): Promise<PluginEvent | null> {
    const processedEvent = await runInstrumentedFunction({
        timeoutContext: () => ({
            event: JSON.stringify(event),
        }),
        func: () => runProcessEvent(runner.hub, event),
        statsKey: 'kafka_queue.single_event',
        timeoutMessage: 'Still running plugins on event. Timeout warning after 30 sec!',
        teamId: event.team_id,
    })

    if (processedEvent) {
        return processedEvent
    } else {
        // processEvent might not return an event. This is expected and plugins, e.g. downsample plugin uses it.
        droppedEventCounter.inc()
        return null
    }
}
