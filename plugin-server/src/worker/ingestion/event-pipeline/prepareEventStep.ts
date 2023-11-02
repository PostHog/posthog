import { PluginEvent } from '@posthog/plugin-scaffold'
import { PreIngestionEvent } from 'types'

import { parseEventTimestamp } from '../timestamps'
import { captureIngestionWarning } from '../utils'
import { EventPipelineRunner } from './runner'

export async function prepareEventStep(runner: EventPipelineRunner, event: PluginEvent): Promise<PreIngestionEvent> {
    const { team_id, uuid } = event
    const tsParsingIngestionWarnings: Promise<void>[] = []
    const invalidTimestampCallback = function (type: string, details: Record<string, any>) {
        // TODO: make that metric name more generic when transitionning to prometheus
        runner.hub.statsd?.increment('process_event_invalid_timestamp', { teamId: String(team_id), type: type })

        tsParsingIngestionWarnings.push(captureIngestionWarning(runner.hub.db, team_id, type, details))
    }

    const preIngestionEvent = await runner.hub.eventsProcessor.processEvent(
        String(event.distinct_id),
        event,
        team_id,
        parseEventTimestamp(event, invalidTimestampCallback),
        uuid! // it will throw if it's undefined,
    )
    await Promise.all(tsParsingIngestionWarnings)

    return preIngestionEvent
}
