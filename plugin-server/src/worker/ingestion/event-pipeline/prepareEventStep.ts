import { PluginEvent } from '@posthog/plugin-scaffold'

import { PreIngestionEvent } from '~/src/types'
import { captureException } from '@sentry/node'

import { status } from '../../../utils/status'
import { parseEventTimestamp } from '../timestamps'
import { captureIngestionWarning } from '../utils'
import { invalidTimestampCounter } from './metrics'
import { processAiEvent } from './processAiEvent'
import { EventPipelineRunner } from './runner'

export async function prepareEventStep(
    runner: EventPipelineRunner,
    event: PluginEvent,
    processPerson: boolean
): Promise<PreIngestionEvent> {
    const { team_id, uuid } = event
    const tsParsingIngestionWarnings: Promise<void>[] = []
    const invalidTimestampCallback = function (type: string, details: Record<string, any>) {
        invalidTimestampCounter.labels(type).inc()

        tsParsingIngestionWarnings.push(captureIngestionWarning(runner.hub.db.kafkaProducer, team_id, type, details))
    }

    if (event.event === '$ai_generation' || event.event === '$ai_embedding') {
        try {
            event = processAiEvent(event)
        } catch (error) {
            // NOTE: Whilst this is pre-production we want to make it as optional as possible
            // so we don't block the pipeline if it fails
            captureException(error)
            status.error(error)
        }
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

    return preIngestionEvent
}
