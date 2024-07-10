import { PluginEvent } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'
import { Person } from 'types'

import { PersonState } from '../person-state'
import { EventPipelineRunner } from './runner'

export async function processPersonsStep(
    runner: EventPipelineRunner,
    event: PluginEvent,
    timestamp: DateTime,
    processPerson: boolean
): Promise<[PluginEvent, Person, Promise<void>]> {
    const [person, kafkaAck] = await new PersonState(
        event,
        event.team_id,
        String(event.distinct_id),
        timestamp,
        processPerson,
        runner.hub.db
    ).update()

    return [event, person, kafkaAck]
}
