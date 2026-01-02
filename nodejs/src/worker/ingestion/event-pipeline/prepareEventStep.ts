import { PluginEvent } from '@posthog/plugin-scaffold'

import { PreIngestionEvent, Team } from '~/types'

import { AI_EVENT_TYPES, processAiEvent } from '../../../ingestion/ai-costs/process-ai-event'
import { KafkaProducerWrapper } from '../../../kafka/producer'
import { logger } from '../../../utils/logger'
import { captureException } from '../../../utils/posthog'
import { GroupStoreForBatch } from '../groups/group-store-for-batch.interface'
import { EventsProcessor } from '../process-event'
import { parseEventTimestamp } from '../timestamps'
import { captureIngestionWarning } from '../utils'
import { invalidTimestampCounter } from './metrics'

export async function prepareEventStep(
    kafkaProducer: KafkaProducerWrapper,
    eventsProcessor: EventsProcessor,
    groupStoreForBatch: GroupStoreForBatch,
    event: PluginEvent,
    processPerson: boolean,
    team: Team
): Promise<PreIngestionEvent> {
    const { team_id, uuid } = event
    const tsParsingIngestionWarnings: Promise<unknown>[] = []
    const invalidTimestampCallback = function (type: string, details: Record<string, any>) {
        invalidTimestampCounter.labels(type).inc()

        tsParsingIngestionWarnings.push(captureIngestionWarning(kafkaProducer, team_id, type, details))
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

    const preIngestionEvent = await eventsProcessor.processEvent(
        String(event.distinct_id),
        event,
        team,
        parseEventTimestamp(event, invalidTimestampCallback),
        uuid!, // it will throw if it's undefined,
        processPerson,
        groupStoreForBatch
    )
    await Promise.all(tsParsingIngestionWarnings)

    return preIngestionEvent
}
