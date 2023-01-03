import { PluginEvent } from '@posthog/plugin-scaffold'

import { normalizeEvent } from '../../../utils/event'
import { LazyPersonContainer } from '../lazy-person-container'
import { updatePersonState } from '../person-state'
import { parseEventTimestamp } from '../timestamps'
import { EventPipelineRunner, StepResult } from './runner'

export async function processPersonsStep(
    runner: EventPipelineRunner,
    pluginEvent: PluginEvent,
    personContainer: LazyPersonContainer
): Promise<StepResult> {
    const event = normalizeEvent(pluginEvent)

    // TODO: Have the snapshot events pipeline be completely separate
    // from all other events
    if (['$snapshot', '$performance_event'].includes(event.event)) {
        return runner.nextStep('prepareEventStep', event, personContainer)
    }

    const timestamp = parseEventTimestamp(event)

    const newPersonContainer: LazyPersonContainer = await updatePersonState(
        event,
        event.team_id,
        String(event.distinct_id),
        timestamp,
        runner.hub.db,
        runner.hub.statsd,
        runner.hub.personManager,
        personContainer
    )

    return runner.nextStep('prepareEventStep', event, newPersonContainer)
}
