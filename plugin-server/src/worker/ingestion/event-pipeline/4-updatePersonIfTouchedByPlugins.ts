import { PluginEvent } from '@posthog/plugin-scaffold'
import equal from 'fast-deep-equal'

import { Person } from '../../../types'
import { normalizeEvent } from '../../../utils/event'
import { updatePropertiesPersonState } from '../person-state'
import { parseEventTimestamp } from '../timestamps'
import { ForwardedPersonData } from './2-processPersonsStep'
import { EventPipelineRunner, StepResult } from './runner'

export async function updatePersonIfTouchedByPlugins(
    runner: EventPipelineRunner,
    pluginEvent: PluginEvent,
    forwardedPersonData: ForwardedPersonData
): Promise<StepResult> {
    // :TRICKY: plugins might have modified the event, so re-sanitize
    const event = normalizeEvent(pluginEvent)

    let person: Person | undefined = forwardedPersonData.person
    // :TRICKY: pluginsProcessEventStep might have added/removed $set or $set_once properties.
    if (
        hasPropertyChanged('$set', event, forwardedPersonData) ||
        hasPropertyChanged('$set_once', event, forwardedPersonData) ||
        hasPropertyChanged('$unset', event, forwardedPersonData)
    ) {
        const timestamp = parseEventTimestamp(event, runner.hub.statsd)
        person = await updatePropertiesPersonState(
            event,
            event.team_id,
            String(event.distinct_id),
            timestamp,
            runner.hub.db,
            runner.hub.statsd,
            runner.hub.personManager,
            person
        )
    }

    return runner.nextStep('prepareEventStep', event, person)
}

function hasPropertyChanged(
    property: '$set' | '$set_once' | '$unset',
    event: PluginEvent,
    forwardedPersonData: ForwardedPersonData
): boolean {
    return (
        !!event.properties && !equal(event.properties[property], forwardedPersonData.personUpdateProperties[property])
    )
}
