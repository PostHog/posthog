import { PluginEvent } from '@posthog/plugin-scaffold'

import { Person } from '../../../types'
import { normalizeEvent } from '../../../utils/event'
import { updatePersonState } from '../person-state'
import { parseEventTimestamp } from '../timestamps'
import { EventPipelineRunner, StepResult } from './runner'

export async function processPersonsStep(
    runner: EventPipelineRunner,
    pluginEvent: PluginEvent,
    person: Person | undefined
): Promise<StepResult> {
    const event = normalizeEvent(pluginEvent)
    const timestamp = parseEventTimestamp(event, runner.hub.statsd)

    const personInfo: Person | undefined = await updatePersonState(
        // can this return undefined?
        event,
        event.team_id,
        String(event.distinct_id),
        timestamp,
        runner.hub.db,
        runner.hub.statsd,
        runner.hub.personManager,
        person
    )

    return runner.nextStep('prepareEventStep', event, personInfo)
}
