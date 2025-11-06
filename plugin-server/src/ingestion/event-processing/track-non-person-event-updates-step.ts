import { setUsageInNonPersonEventsCounter } from '../../main/ingestion-queues/metrics'
import { PipelineEvent } from '../../types'
import { BatchProcessingStep } from '../pipelines/base-batch-pipeline'
import { PipelineResult, ok } from '../pipelines/results'

const PERSON_EVENTS = new Set(['$set', '$identify', '$create_alias', '$merge_dangerously', '$groupidentify'])
const KNOWN_SET_EVENTS = new Set([
    '$feature_interaction',
    '$feature_enrollment_update',
    'survey dismissed',
    'survey sent',
])

const trackIfNonPersonEventUpdatesPersons = (event: PipelineEvent): void => {
    if (
        !PERSON_EVENTS.has(event.event) &&
        !KNOWN_SET_EVENTS.has(event.event) &&
        (event.properties?.$set || event.properties?.$set_once || event.properties?.$unset)
    ) {
        setUsageInNonPersonEventsCounter.inc()
    }
}

export function createTrackNonPersonEventUpdatesStep<T extends { event: PipelineEvent }>(): BatchProcessingStep<T, T> {
    return async function trackNonPersonEventUpdatesStep(events: T[]): Promise<PipelineResult<T>[]> {
        for (const event of events) {
            trackIfNonPersonEventUpdatesPersons(event.event)
        }

        return Promise.resolve(events.map((event) => ok(event)))
    }
}
