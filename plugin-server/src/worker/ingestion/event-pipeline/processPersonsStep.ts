import { PluginEvent } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'
import { Person } from 'types'

import { normalizeEvent } from '../../../utils/event'
import { status } from '../../../utils/status'
import { DeferredPersonOverrideWriter, PersonState } from '../person-state'
import { parseEventTimestamp } from '../timestamps'
import { EventPipelineRunner } from './runner'

export async function processPersonsStep(
    runner: EventPipelineRunner,
    pluginEvent: PluginEvent
): Promise<[PluginEvent, Person]> {
    let event: PluginEvent
    let timestamp: DateTime
    try {
        event = normalizeEvent(pluginEvent)
        timestamp = parseEventTimestamp(event)
    } catch (error) {
        status.warn('⚠️', 'Failed normalizing event', { team_id: pluginEvent.team_id, uuid: pluginEvent.uuid, error })
        throw error
    }

    let overridesWriter: DeferredPersonOverrideWriter | undefined = undefined
    if (runner.poEEmbraceJoin) {
        overridesWriter = new DeferredPersonOverrideWriter(runner.hub.db.postgres)
    }

    const person = await new PersonState(
        event,
        event.team_id,
        String(event.distinct_id),
        timestamp,
        runner.hub.db,
        overridesWriter
    ).update()

    return [event, person]
}
