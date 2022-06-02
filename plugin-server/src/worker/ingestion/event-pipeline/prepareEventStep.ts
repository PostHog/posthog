import { PluginEvent } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { EventPipelineRunner, StepResult } from './runner'

export async function prepareEventStep(runner: EventPipelineRunner, event: PluginEvent): Promise<StepResult> {
    const { ip, site_url, team_id, now, sent_at, uuid } = event
    const distinctId = String(event.distinct_id)
    const preIngestionEvent = await runner.hub.eventsProcessor.processEvent(
        distinctId,
        ip,
        event,
        team_id,
        DateTime.fromISO(now),
        sent_at ? DateTime.fromISO(sent_at) : null,
        uuid! // it will throw if it's undefined,
    )

    await runner.hub.siteUrlManager.updateIngestionSiteUrl(site_url)

    if (preIngestionEvent && preIngestionEvent.event !== '$snapshot') {
        return runner.nextStep('emitToBufferStep', preIngestionEvent)
    } else if (preIngestionEvent && preIngestionEvent.event === '$snapshot') {
        return runner.nextStep('runAsyncHandlersStep', preIngestionEvent, undefined)
    } else {
        return null
    }
}
