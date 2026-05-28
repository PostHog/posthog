import { EventHeaders, Team } from '../../../types'
import { IngestionOutputs } from '../../outputs/ingestion-outputs'
import { BeforeBatchStep } from '../../pipelines/batching-pipeline'
import { PipelineResult, drop, ok } from '../../pipelines/results'
import { ProcessingStep } from '../../pipelines/steps'
import { EventFilterManager, evaluateFilterTree } from '../event-filters'
import { EventFiltersBatchAppMetrics } from '../event-filters/batch-app-metrics'
import { eventFiltersEventsEvaluated } from '../event-filters/metrics'
import { AppMetricsOutput } from '../outputs'

export interface EventFiltersBatchContext {
    eventFiltersBatchAppMetrics: EventFiltersBatchAppMetrics
}

/**
 * BeforeBatch step that creates an EventFiltersBatchAppMetrics instance
 * and attaches it to the batch context and each element.
 */
export function createEventFiltersBatchAppMetricsBeforeBatchStep<TInput, CInput>(
    outputs: IngestionOutputs<AppMetricsOutput>
): BeforeBatchStep<TInput, CInput, EventFiltersBatchContext> {
    return function eventFiltersBatchAppMetricsBeforeBatchStep(input) {
        const eventFiltersBatchAppMetrics = new EventFiltersBatchAppMetrics(outputs)
        const batchContext: EventFiltersBatchContext = { eventFiltersBatchAppMetrics }

        const elements = input.elements.map((element) => ({
            result: {
                ...element.result,
                value: { ...element.result.value, ...batchContext },
            },
            context: element.context,
        }))

        return Promise.resolve(ok({ elements, batchContext }))
    }
}

export interface ApplyEventFiltersInput {
    team: Team
    headers: EventHeaders
    eventFiltersBatchAppMetrics: EventFiltersBatchAppMetrics
}

/**
 * Creates a pipeline step that evaluates customer-configured event filters.
 *
 * Uses event headers (event name, distinct_id) so it can run before the Kafka
 * message is parsed into a full event — avoiding wasted work on dropped events.
 *
 * In "live" mode, matching events are dropped and a "dropped" metric is recorded.
 * In "dry_run" mode, matching events are NOT dropped but a "would_be_dropped" metric
 * is recorded, allowing customers to verify their filter before enabling it.
 *
 * Metrics are aggregated per batch via EventFiltersBatchAppMetrics rather than
 * producing individual Kafka messages per event.
 */
export function createApplyEventFiltersStep<T extends ApplyEventFiltersInput>(
    manager: EventFilterManager
): ProcessingStep<T, T> {
    return function applyEventFiltersStep(input: T): Promise<PipelineResult<T>> {
        const filter = manager.getFilter(input.team.id)

        if (!filter) {
            return Promise.resolve(ok(input))
        }

        const matched = evaluateFilterTree(filter.filter_tree, {
            event_name: input.headers.event,
            distinct_id: input.headers.distinct_id,
        })

        if (matched) {
            const isLive = filter.mode === 'live'
            const metricName = isLive ? 'dropped' : 'would_be_dropped'

            input.eventFiltersBatchAppMetrics.increment(input.team.id, filter.id, metricName)

            // Only drop in live mode — any other mode (dry_run, or unexpected values)
            // lets the event through to avoid accidental data loss
            if (isLive) {
                eventFiltersEventsEvaluated.inc({ outcome: 'dropped' })
                return Promise.resolve(drop('event_filter'))
            }

            eventFiltersEventsEvaluated.inc({ outcome: 'shadow_dropped' })
            return Promise.resolve(ok(input))
        }

        eventFiltersEventsEvaluated.inc({ outcome: 'ingested' })
        return Promise.resolve(ok(input))
    }
}

/**
 * AfterBatch processing step that flushes aggregated event filter app metrics.
 * Produces one Kafka message per unique (teamId, filterId, metricName) combination.
 */
export function createFlushEventFiltersBatchAppMetricsStep<
    T extends { batchContext: EventFiltersBatchContext },
>(): ProcessingStep<T, T> {
    return function flushEventFiltersBatchAppMetricsStep(input: T): Promise<PipelineResult<T>> {
        return Promise.resolve(ok(input, [input.batchContext.eventFiltersBatchAppMetrics.flush()]))
    }
}
