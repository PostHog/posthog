import { PluginEvent } from '@posthog/plugin-scaffold'
import { Person } from 'types'

import { normalizeEvent } from '../../../utils/event'
import { PersonState } from '../person-state'
import { parseEventTimestamp } from '../timestamps'
import { EventPipelineRunner } from './runner'

export async function processPersonsStep(
    runner: EventPipelineRunner,
    pluginEvent: PluginEvent
): Promise<[PluginEvent, Person]> {
    const event = normalizeEvent(pluginEvent)

    const timestamp = parseEventTimestamp(event)

    const person = await new PersonState(
        event,
        event.team_id,
        String(event.distinct_id),
        timestamp,
        runner.hub.db,
        runner.hub.statsd,
        runner.poEEmbraceJoin
    ).update()

    return [event, person]
}
