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
    if (pluginEvent.event === '$$delete_person') {
        console.log('HEREEEEE')
        console.log('HEREEEEE')
        console.log('HEREEEEE')
        console.log('HEREEEEE')
        person =
            person ||
            (await runner.hub.db.fetchPersonById(pluginEvent.team_id, pluginEvent.properties?.['$$person_id']))
        console.log(person)
        if (person) {
            await runner.hub.db.deletePerson(person)
        }
        return null
    }

    const event = normalizeEvent(pluginEvent)
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

    return runner.nextStep('prepareEventStep', event, personInfo)
}
