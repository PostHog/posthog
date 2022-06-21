import { PluginEvent } from '@posthog/plugin-scaffold'

import { runInstrumentedFunction } from '../../../main/utils'
import { runProcessEvent } from '../../plugins/run'
import { ForwardedPersonData } from './2-processPersonsStep'
import { EventPipelineRunner, StepResult } from './runner'

export async function pluginsProcessEventStep(
    runner: EventPipelineRunner,
    event: PluginEvent,
    forwardedPersonData: ForwardedPersonData
): Promise<StepResult> {
    let processedEvent: PluginEvent | null = event

    // run processEvent on all events that are not $snapshot
    if (event.event !== '$snapshot') {
        processedEvent = await runInstrumentedFunction({
            server: runner.hub,
            event,
            func: (event) => runProcessEvent(runner.hub, event),
            statsKey: 'kafka_queue.single_event',
            timeoutMessage: 'Still running plugins on event. Timeout warning after 30 sec!',
        })
    }

    if (processedEvent) {
        return runner.nextStep('updatePersonIfTouchedByPlugins', processedEvent, forwardedPersonData)
    } else {
        // processEvent might not return an event. This is expected and plugins, e.g. downsample plugin uses it.
        runner.hub.statsd?.increment('kafka_queue.dropped_event', {
            teamID: String(event.team_id),
        })
        return null
    }
}
