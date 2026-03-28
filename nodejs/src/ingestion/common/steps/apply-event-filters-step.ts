import { EventHeaders, PipelineEvent, Team, TimestampFormat } from '../../../types'
import { castTimestampOrNow } from '../../../utils/utils'
import { IngestionOutputs } from '../../outputs/ingestion-outputs'
import { PipelineResult, drop, ok } from '../../pipelines/results'
import { ProcessingStep } from '../../pipelines/steps'
import { EventFilterManager, evaluateFilterTree } from '../event-filters'
import { APP_METRICS_OUTPUT, AppMetricsOutput } from '../outputs'

export interface ApplyEventFiltersInput {
    event: PipelineEvent
    team: Team
    headers: EventHeaders
}

/**
 * Creates a pipeline step that evaluates customer-configured event filters.
 *
 * In "live" mode, matching events are dropped and a "dropped" metric is recorded.
 * In "dry_run" mode, matching events are NOT dropped but a "would_be_dropped" metric
 * is recorded, allowing customers to verify their filter before enabling it.
 */
export function createApplyEventFiltersStep<T extends ApplyEventFiltersInput>(
    manager: EventFilterManager,
    outputs: IngestionOutputs<AppMetricsOutput>
): ProcessingStep<T, T> {
    return function applyEventFiltersStep(input: T): Promise<PipelineResult<T>> {
        const filter = manager.getFilter(input.team.id)

        if (!filter) {
            return Promise.resolve(ok(input))
        }

        const matched = evaluateFilterTree(filter.filter_tree, {
            event_name: input.event.event,
            distinct_id: input.event.distinct_id ?? input.headers.distinct_id ?? undefined,
        })

        if (matched) {
            const isLive = filter.mode === 'live'
            const metricMessage = {
                value: Buffer.from(
                    JSON.stringify({
                        team_id: input.team.id,
                        timestamp: castTimestampOrNow(null, TimestampFormat.ClickHouse),
                        app_source: 'event_filter',
                        app_source_id: filter.id,
                        metric_kind: 'other',
                        metric_name: isLive ? 'dropped' : 'would_be_dropped',
                        count: 1,
                    })
                ),
                key: Buffer.from(`${input.team.id}`),
            }

            const sideEffect = outputs.produce(APP_METRICS_OUTPUT, metricMessage)

            // Only drop in live mode — any other mode (dry_run, or unexpected values)
            // lets the event through to avoid accidental data loss
            if (isLive) {
                return Promise.resolve(drop('event_filter', [sideEffect]))
            }

            return Promise.resolve(ok(input, [sideEffect]))
        }

        return Promise.resolve(ok(input))
    }
}
