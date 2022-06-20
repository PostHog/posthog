import { PluginEvent, Properties } from '@posthog/plugin-scaffold'

import { IngestionPersonData } from '../../../types'
import { PersonState } from '../person-state'
import { parseEventTimestamp } from '../timestamps'
import { EventPipelineRunner, StepResult } from './runner'

export interface ForwardedPersonData {
    person: IngestionPersonData | undefined
    personUpdateProperties: {
        $set?: Properties
        $set_once?: Properties
        $unset: string[]
    }
}

export async function upsertPersonsStep(
    runner: EventPipelineRunner,
    event: PluginEvent,
    person: IngestionPersonData | undefined
): Promise<StepResult> {
    const timestamp = parseEventTimestamp(event, runner.hub.statsd)

    const personState = new PersonState(
        event,
        event.team_id,
        String(event.distinct_id),
        timestamp,
        runner.hub.db,
        runner.hub.statsd,
        runner.hub.personManager,
        person
    )
    const personInfo: IngestionPersonData | undefined = await personState.update()

    return runner.nextStep('pluginsProcessEventStep', event, {
        person: personInfo,
        // :TRICKY: We forward (and clone) properties that are updated to detect whether we need to update properties again
        //    at a later step
        personUpdateProperties: {
            $set: { ...event.properties!.$set },
            $set_once: { ...event.properties!.$set_once },
            $unset: { ...event.properties!.$unset },
        },
    })
}
