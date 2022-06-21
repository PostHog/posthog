import { PluginEvent, Properties } from '@posthog/plugin-scaffold'

import { Person } from '../../../types'
import { updatePersonState } from '../person-state'
import { parseEventTimestamp } from '../timestamps'
import { EventPipelineRunner, StepResult } from './runner'

export interface ForwardedPersonData {
    person: Person | undefined
    personUpdateProperties: {
        $set?: Properties
        $set_once?: Properties
        $unset?: string[]
    }
}

export async function processPersonsStep(
    runner: EventPipelineRunner,
    event: PluginEvent,
    person: Person | undefined
): Promise<StepResult> {
    const timestamp = parseEventTimestamp(event, runner.hub.statsd)

    const personInfo: Person | undefined = await updatePersonState(
        event,
        event.team_id,
        String(event.distinct_id),
        timestamp,
        runner.hub.db,
        runner.hub.statsd,
        runner.hub.personManager,
        person
    )

    return runner.nextStep('pluginsProcessEventStep', event, {
        person: personInfo,
        // :TRICKY: We forward (and clone) properties that are updated to detect whether we need to update properties again
        //    at a later step
        // Note: We assume normalizeEvent has been called here.
        personUpdateProperties: {
            $set: { ...event.properties!.$set },
            $set_once: { ...event.properties!.$set_once },
            $unset: { ...event.properties!.$unset },
        },
    })
}
