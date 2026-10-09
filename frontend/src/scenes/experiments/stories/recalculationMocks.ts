import type { Mocks } from '~/mocks/utils'

import type {
    ExperimentMetricsRecalculationJobApi,
    ExperimentMetricsRecalculationLatestApi,
    ExperimentMetricsRecalculationRunApi,
    MetricRecalculationResultApi,
} from 'products/experiments/frontend/generated/api.schemas'

/** The parts of an experiment fixture the run reads: every metric uuid, inline and shared, in both sections. */
type ExperimentFixture = {
    id: number | string
    metrics?: { uuid?: string }[]
    metrics_secondary?: { uuid?: string }[]
    saved_metrics?: { query?: { uuid?: string } }[]
}

/** A result fixture is a cached experiment query response; `last_refresh` stamps the run's window. */
type ResultFixture = { last_refresh?: string | null } & Record<string, unknown>

const RUN_ID = 'storybook-recalculation'

type MetricType = 'mean' | 'funnel' | 'ratio'
type ExperimentWithMetricTypes = ExperimentFixture & {
    metrics?: { uuid?: string; metric_type?: string }[]
    metrics_secondary?: { uuid?: string; metric_type?: string }[]
}

/** Resolves each metric of the experiment to the result fixture for its metric type. */
export function resultsByMetricType(
    experiment: ExperimentWithMetricTypes,
    fixtures: Partial<Record<MetricType, ResultFixture>>
): (metricUuid: string) => ResultFixture | null {
    const metrics = [...(experiment.metrics ?? []), ...(experiment.metrics_secondary ?? [])]
    return (metricUuid) => {
        const metricType = metrics.find((metric) => metric.uuid === metricUuid)?.metric_type as MetricType | undefined
        return (metricType && fixtures[metricType]) || null
    }
}

/**
 * Handlers for the recalculation endpoints experimentMetricsLogic calls on mount: the latest run, the create
 * POST, and the retrieve by id. All three answer with one completed run that covers every metric of the
 * experiment, so no cold run or heal starts and the table renders the fixtures at once. `resultFor` picks the
 * result fixture per metric uuid; `null` records that metric as failed, which keeps an error story an error.
 */
export function recalculationMocks(
    experiment: ExperimentFixture,
    resultFor: (metricUuid: string) => ResultFixture | null
): Mocks {
    const metricUuids = [
        ...(experiment.metrics ?? []).map((metric) => metric.uuid),
        ...(experiment.metrics_secondary ?? []).map((metric) => metric.uuid),
        ...(experiment.saved_metrics ?? []).map((savedMetric) => savedMetric.query?.uuid),
    ].filter((uuid): uuid is string => !!uuid)

    const results: MetricRecalculationResultApi[] = metricUuids.map((metricUuid) => {
        const result = resultFor(metricUuid)
        return result
            ? { metric_uuid: metricUuid, status: 'completed', result, error_message: null }
            : { metric_uuid: metricUuid, status: 'failed', result: null, error_message: 'Metric failed to compute' }
    })
    const failedUuids = results.filter(({ status }) => status === 'failed').map(({ metric_uuid }) => metric_uuid)
    // The legacy loader showed each result's own refresh stamp; the run's window is the freshest of them.
    const queryTo =
        results
            .map(({ result }) => (result as ResultFixture | null)?.last_refresh ?? null)
            .filter((stamp): stamp is string => !!stamp)
            .sort()
            .at(-1) ?? null

    const run: ExperimentMetricsRecalculationRunApi = {
        id: RUN_ID,
        experiment_id: Number(experiment.id),
        status: failedUuids.length === metricUuids.length && metricUuids.length > 0 ? 'failed' : 'completed',
        total_metrics: metricUuids.length,
        completed_metrics: metricUuids.length - failedUuids.length,
        failed_metrics: failedUuids.length,
        metric_errors: Object.fromEntries(
            failedUuids.map((uuid) => [
                uuid,
                { step: 'calculate', message: 'Metric failed to compute', retriable: false },
            ])
        ),
        created_at: queryTo ?? new Date(0).toISOString(),
        started_at: queryTo,
        completed_at: queryTo,
        query_to: queryTo,
        metric_retries: {},
        results,
        rows_read: null,
        estimated_rows_total: null,
    }
    const latest: ExperimentMetricsRecalculationLatestApi = { ...run, active_run: null, result_source: 'recalculation' }
    const job: ExperimentMetricsRecalculationJobApi = { ...run, is_existing: true }
    const base = `/api/projects/:team_id/experiments/${experiment.id}/metrics_recalculation`

    return {
        get: {
            [`${base}/latest/`]: latest,
            [`${base}/:recalculationId/`]: run,
        },
        post: {
            [`${base}/`]: [201, job],
        },
    }
}
