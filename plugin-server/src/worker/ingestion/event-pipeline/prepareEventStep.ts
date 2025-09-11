import { PluginEvent } from '@posthog/plugin-scaffold'

import { PreIngestionEvent } from '~/types'

import { AI_EVENT_TYPES, processAiEvent } from '../../../ingestion/ai-costs/process-ai-event'
import { logger } from '../../../utils/logger'
import { captureException } from '../../../utils/posthog'
import { parseEventTimestamp } from '../timestamps'
import { captureIngestionWarning } from '../utils'
import { invalidTimestampCounter } from './metrics'
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

    if (AI_EVENT_TYPES.has(event.event)) {
        try {
            event = processAiEvent(event)
        } catch (error) {
            // NOTE: Whilst this is pre-production we want to make it as optional as possible
            // so we don't block the pipeline if it fails
            captureException(error)
            logger.error(error)
        }
    }

    const preIngestionEvent = await runner.eventsProcessor.processEvent(
        String(event.distinct_id),
        event,
        team_id,
        parseEventTimestamp(event, invalidTimestampCallback),
        uuid!, // it will throw if it's undefined,
        processPerson,
        runner.groupStoreForBatch
    )
    await Promise.all(tsParsingIngestionWarnings)

    return preIngestionEvent
}
