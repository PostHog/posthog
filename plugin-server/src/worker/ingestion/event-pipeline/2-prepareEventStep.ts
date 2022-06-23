import { PluginEvent } from '@posthog/plugin-scaffold'

import { normalizeEvent } from '../../../utils/event'
import { parseEventTimestamp } from '../timestamps'
import { EventPipelineRunner, StepResult } from './runner'

export async function prepareEventStep(runner: EventPipelineRunner, event: PluginEvent): Promise<StepResult> {
    // :TRICKY: plugins might have modified the event, so re-sanitize
    const { ip, site_url, team_id, uuid } = normalizeEvent(event)
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
        return runner.nextStep('emitToBufferStep', preIngestionEvent)
    } else if (preIngestionEvent && preIngestionEvent.event === '$snapshot') {
        return runner.nextStep('runAsyncHandlersStep', preIngestionEvent)
    } else {
        return null
    }
}
