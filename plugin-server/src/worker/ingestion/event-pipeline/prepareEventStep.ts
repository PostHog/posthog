import { PluginEvent } from '@posthog/plugin-scaffold'

import { PreIngestionEvent } from '~/src/types'

import { processAiEvent } from '../../../ingestion/ai-costs/process-ai-event'
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

    if (event.event === '$ai_generation' || event.event === '$ai_embedding') {
        try {
            event = processAiEvent(event)
        } catch (error) {
            // NOTE: Whilst this is pre-production we want to make it as optional as possible
            // so we don't block the pipeline if it fails
            captureException(error)
            logger.error(error)
        }
    }

    // submits ingestion warnings if timestamp is invalid, skewed, or historical
    // event submission carries event.timestamp more recent than 24 hours. The
    // historical check is performed in parseEventTimestamp, but prior to skew adjustments
    // since event stamp the user submitted will be the one they'll expect us to measure by
    const isHistoricalEvent = runner.hub.INGESTION_CONSUMER_CONSUME_TOPIC.includes('historical')
    const parsedTimestamp = parseEventTimestamp(team_id, event, isHistoricalEvent, invalidTimestampCallback)

    const preIngestionEvent = await runner.eventsProcessor.processEvent(
        String(event.distinct_id),
        event,
        team_id,
        parsedTimestamp,
        uuid!, // it will throw if it's undefined,
        processPerson,
        runner.groupStoreForDistinctId
    )
    await Promise.all(tsParsingIngestionWarnings)

    return preIngestionEvent
}
