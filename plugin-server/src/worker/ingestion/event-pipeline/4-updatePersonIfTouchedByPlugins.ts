import { PluginEvent } from '@posthog/plugin-scaffold'
import equal from 'fast-deep-equal'

import { IngestionPersonData } from '../../../types'
import { PersonState } from '../person-state'
import { parseEventTimestamp } from '../timestamps'
import { ForwardedPersonData } from './2-upsertPersonsStep'
import { EventPipelineRunner, StepResult } from './runner'

export async function updatePersonIfTouchedByPlugins(
    runner: EventPipelineRunner,
    event: PluginEvent,
    forwardedPersonData: ForwardedPersonData
): Promise<StepResult> {
    let person: IngestionPersonData | undefined = forwardedPersonData.person
    // :TRICKY: pluginsProcessEventStep might have added/removed $set or $set_once properties.
    if (
        hasPropertyChanged('$set', event, forwardedPersonData) ||
        hasPropertyChanged('$set_once', event, forwardedPersonData)
    ) {
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
        person = await personState.updateProperties()
    }

    return runner.nextStep('prepareEventStep', event, person)
}

function hasPropertyChanged(
    property: '$set' | '$set_once',
    event: PluginEvent,
    forwardedPersonData: ForwardedPersonData
): boolean {
    return (
        event.properties &&
        event.properties[property] &&
        !equal(event.properties[property], forwardedPersonData.personUpdateProperties[property])
    )
}
