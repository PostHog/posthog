import { PluginEvent } from '@posthog/plugin-scaffold'

import { normalizeEvent } from '../../../utils/event'
import { LazyPersonContainer } from '../lazy-person-container'
import { updatePersonState } from '../person-state'
import { parseEventTimestamp } from '../timestamps'
import { EventPipelineRunner } from './runner'

export async function processPersonsStep(
    runner: EventPipelineRunner,
    pluginEvent: PluginEvent,
    personContainer: LazyPersonContainer
): Promise<[PluginEvent, LazyPersonContainer]> {
    const event = normalizeEvent(pluginEvent)

    const timestamp = parseEventTimestamp(event)

    // TODO: handle runner.poEEmbraceJoinEnabled
    const newPersonContainer: LazyPersonContainer = await updatePersonState(
        event,
        event.team_id,
        String(event.distinct_id),
        timestamp,
        runner.hub.db,
        runner.hub.statsd,
        runner.hub.personManager,
        personContainer,
        runner.poEEmbraceJoin
    )

    return [event, newPersonContainer]
}
