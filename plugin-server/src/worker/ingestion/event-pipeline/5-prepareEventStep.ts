import { PluginEvent } from '@posthog/plugin-scaffold'

import { PostIngestionEvent } from '../../../types'
import { LazyPersonContainer } from '../lazy-person-container'
import { parseEventTimestamp } from '../timestamps'
import { EventPipelineRunner, StepResult } from './runner'

export async function prepareEventStep(
    runner: EventPipelineRunner,
    event: PluginEvent,
    personContainer: LazyPersonContainer
): Promise<StepResult> {
    const { ip, site_url, team_id, uuid } = event
    const invalidTimestampCallback = function () {
        runner.hub.statsd?.increment('process_event_invalid_timestamp', { teamId: String(team_id) })
    }
    const preIngestionEvent = await runner.hub.eventsProcessor.processEvent(
        String(event.distinct_id),
        ip,
        event,
        team_id,
        parseEventTimestamp(event, invalidTimestampCallback),
        uuid! // it will throw if it's undefined,
    )

    await runner.hub.siteUrlManager.updateIngestionSiteUrl(site_url)

    if (preIngestionEvent && preIngestionEvent.event !== '$snapshot') {
        return runner.nextStep('createEventStep', preIngestionEvent, personContainer)
    } else if (preIngestionEvent && preIngestionEvent.event === '$snapshot') {
        return runner.nextStep('runAsyncHandlersStep', preIngestionEvent as PostIngestionEvent, personContainer)
    } else {
        return null
    }
}
