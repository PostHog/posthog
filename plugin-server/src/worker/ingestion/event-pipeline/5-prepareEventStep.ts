import { PluginEvent } from '@posthog/plugin-scaffold'

import { IngestionPersonData } from '../../../types'
import { parseEventTimestamp } from '../timestamps'
import { EventPipelineRunner, StepResult } from './runner'

export async function prepareEventStep(
    runner: EventPipelineRunner,
    event: PluginEvent,
    person: IngestionPersonData | undefined
): Promise<StepResult> {
    const { ip, site_url, team_id, uuid } = event
    const preIngestionEvent = await runner.hub.eventsProcessor.processEvent(
        String(event.distinct_id),
        ip,
        event,
        team_id,
        parseEventTimestamp(event, runner.hub.statsd),
        uuid!, // it will throw if it's undefined,
        person
    )

    await runner.hub.siteUrlManager.updateIngestionSiteUrl(site_url)

    if (preIngestionEvent && preIngestionEvent.event !== '$snapshot') {
        return runner.nextStep('createEventStep', preIngestionEvent)
    } else if (preIngestionEvent && preIngestionEvent.event === '$snapshot') {
        return runner.nextStep('runAsyncHandlersStep', preIngestionEvent)
    } else {
        return null
    }
}
