import { PluginEvent } from '@posthog/plugin-scaffold'
import { PreIngestionEvent } from 'types'

import { parseEventTimestamp } from '../timestamps'
import { captureIngestionWarning } from '../utils'
import { invalidTimestampCounter } from './metrics'
import { EventPipelineRunner, StepResult } from './runner'

export async function prepareEventStep(
    runner: EventPipelineRunner,
    event: PluginEvent,
    processPerson: boolean
): Promise<StepResult<PreIngestionEvent>> {
    const { team_id, uuid } = event
    const tsParsingIngestionWarnings: Promise<void>[] = []
    const invalidTimestampCallback = function (type: string, details: Record<string, any>) {
        invalidTimestampCounter.labels(type).inc()

        tsParsingIngestionWarnings.push(captureIngestionWarning(runner.hub.db.kafkaProducer, team_id, type, details))
    }

    const preIngestionEvent = await runner.eventsProcessor.processEvent(
        String(event.distinct_id),
        event,
        team_id,
        parseEventTimestamp(event, invalidTimestampCallback),
        uuid!, // it will throw if it's undefined,
        processPerson
    )
    await Promise.all(tsParsingIngestionWarnings)

    return { result: preIngestionEvent }
}
