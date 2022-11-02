import { PluginEvent } from '@posthog/plugin-scaffold'

import { normalizeEvent } from '../../../utils/event'
import { LazyGroupsContainer } from '../lazy-groups-container'
import { LazyPersonContainer } from '../lazy-person-container'
import { updatePersonState } from '../person-state'
import { parseEventTimestamp } from '../timestamps'
import { EventPipelineRunner, StepResult } from './runner'

export async function processPersonsStep(
    runner: EventPipelineRunner,
    pluginEvent: PluginEvent,
    personContainer: LazyPersonContainer,
    groupsContainer: LazyGroupsContainer
): Promise<StepResult> {
    const event = normalizeEvent(pluginEvent)
    const timestamp = parseEventTimestamp(event, runner.hub.statsd)

    const newPersonContainer: LazyPersonContainer = await updatePersonState(
        event,
        event.team_id,
        String(event.distinct_id),
        timestamp,
        runner.hub.db,
        runner.hub.statsd,
        runner.hub.personManager,
        personContainer
    )

    return runner.nextStep('prepareEventStep', event, newPersonContainer, groupsContainer)
}
