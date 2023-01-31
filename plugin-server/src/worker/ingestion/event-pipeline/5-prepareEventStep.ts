import { PluginEvent } from '@posthog/plugin-scaffold'

import { LazyPersonContainer } from '../lazy-person-container'
import { parseEventTimestamp } from '../timestamps'
import { captureIngestionWarning } from '../utils'
import { EventPipelineRunner, StepResult } from './runner'

export async function prepareEventStep(
    runner: EventPipelineRunner,
    event: PluginEvent,
    personContainer: LazyPersonContainer
): Promise<StepResult> {
    const { ip, site_url, team_id, uuid } = event
    const invalidTimestampCallback = function (type: string, details: Record<string, any>) {
        // TODO: make that metric name more generic when transitionning to prometheus
        runner.hub.statsd?.increment('process_event_invalid_timestamp', { teamId: String(team_id), type: type })

        captureIngestionWarning(runner.hub.db, team_id, type, details)
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

    if (preIngestionEvent) {
        return runner.nextStep('createEventStep', preIngestionEvent, personContainer)
    } else {
        return null
    }
}
