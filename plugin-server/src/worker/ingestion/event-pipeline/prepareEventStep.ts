import { PluginEvent } from '@posthog/plugin-scaffold'
import { PreIngestionEvent } from 'types'

import { parseEventTimestamp } from '../timestamps'
import { captureIngestionWarning } from '../utils'
import { EventPipelineRunner } from './runner'

export async function prepareEventStep(runner: EventPipelineRunner, event: PluginEvent): Promise<PreIngestionEvent> {
    const { ip, team_id, uuid } = event
    const invalidTimestampCallback = async function (type: string, details: Record<string, any>) {
        // TODO: make that metric name more generic when transitionning to prometheus
        runner.hub.statsd?.increment('process_event_invalid_timestamp', { teamId: String(team_id), type: type })

        await captureIngestionWarning(runner.hub.db, team_id, type, details)
    }
    const preIngestionEvent = await runner.hub.eventsProcessor.processEvent(
        String(event.distinct_id),
        ip,
        event,
        team_id,
        await parseEventTimestamp(event, invalidTimestampCallback),
        uuid! // it will throw if it's undefined,
    )

    return preIngestionEvent
}
