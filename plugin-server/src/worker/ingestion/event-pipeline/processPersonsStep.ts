import { PluginEvent } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { Person, Team } from '~/src/types'

import { PersonState } from '../person-state'
import { EventPipelineRunner } from './runner'

export async function processPersonsStep(
    runner: EventPipelineRunner,
    event: PluginEvent,
    team: Team,
    timestamp: DateTime,
    processPerson: boolean,
    measurePersonJsonbSize: number = 0
): Promise<[PluginEvent, Person, Promise<void>]> {
    const [person, kafkaAck] = await new PersonState(
        event,
        team,
        String(event.distinct_id),
        timestamp,
        processPerson,
        runner.hub.db,
        measurePersonJsonbSize
    ).update()

    return [event, person, kafkaAck]
}
