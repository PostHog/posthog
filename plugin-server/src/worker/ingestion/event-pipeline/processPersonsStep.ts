import { PluginEvent } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'
import { Person } from 'types'

import { DeferredPersonOverrideWriter, PersonState } from '../person-state'
import { EventPipelineRunner } from './runner'

export async function processPersonsStep(
    runner: EventPipelineRunner,
    event: PluginEvent,
    timestamp: DateTime,
    processPerson: boolean
): Promise<[PluginEvent, Person]> {
    let overridesWriter: DeferredPersonOverrideWriter | undefined = undefined
    if (runner.poEEmbraceJoin) {
        overridesWriter = new DeferredPersonOverrideWriter(runner.hub.db.postgres)
    }

    const person = await new PersonState(
        event,
        event.team_id,
        String(event.distinct_id),
        timestamp,
        processPerson,
        runner.hub.db,
        runner.hub.lazyPersonCreationTeams(event.team_id),
        overridesWriter
    ).update()

    return [event, person]
}
