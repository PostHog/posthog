import { PluginEvent } from '@posthog/plugin-scaffold'

import { PostIngestionEvent } from '../../../types'
import { status } from '../../../utils/status'
import { LazyPersonContainer } from '../lazy-person-container'
import { parseEventTimestamp } from '../timestamps'
import { EventPipelineRunner, StepResult } from './runner'

export async function prepareEventStep(
    runner: EventPipelineRunner,
    event: PluginEvent,
    personContainer: LazyPersonContainer
): Promise<StepResult> {
    status.debug('🔁', 'Running prepareEventStep', { event: event.event, distinct_id: event.distinct_id })
    const { ip, site_url, team_id, uuid } = event
    const preIngestionEvent = await runner.hub.eventsProcessor.processEvent(
        String(event.distinct_id),
        ip,
        event,
        team_id,
        parseEventTimestamp(event, runner.hub.statsd),
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
