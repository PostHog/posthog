import { PluginEvent } from '@posthog/plugin-scaffold'

import { IngestionEvent, IngestionPersonData } from '../../../types'
import { normalizeEvent } from '../../../utils/event'
import { parseEventTimestamp } from '../timestamps'
import { EventPipelineRunner, StepResult } from './runner'

export async function prepareEventStep(
    runner: EventPipelineRunner,
    event: PluginEvent,
    person: IngestionPersonData | undefined
): Promise<StepResult> {
    // :TRICKY: plugins might have modified the event, so re-sanitize
    const { ip, site_url, team_id, uuid } = normalizeEvent(event)
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
        return runner.nextStep('runAsyncHandlersStep', preIngestionEvent as IngestionEvent)
    } else {
        return null
    }
}
