import { Counter, Gauge, Histogram } from 'prom-client'

import { AppMetricsOutput, LOG_ENTRIES_OUTPUT, LogEntriesOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { AppMetricsAggregator } from '~/common/services/app-metrics-aggregator'
import { safeClickhouseString } from '~/common/utils/db/utils'
import { logger } from '~/common/utils/logger'
import { captureException } from '~/common/utils/posthog'

import {
    CyclotronJobInvocationHogFlow,
    CyclotronJobInvocationHogFunction,
    CyclotronJobInvocationResult,
    LogEntry,
    LogEntrySerialized,
    MetricLogSource,
    MinimalAppMetric,
} from '../../types'
import { fixLogDeduplication } from '../../utils'

const counterHogFunctionMetric = new Counter({
    name: 'cdp_hog_function_metric',
    help: 'A function invocation was evaluated with an outcome',
    labelNames: ['metric_kind', 'metric_name'],
})

export const hogFunctionExecutionTimeSummary = new Histogram({
    name: 'cdp_hog_function_duration',
    help: 'Processing time of hog function execution by kind',
    labelNames: ['kind'],
})

const hogFunctionMonitoringPendingMessages = new Gauge({
    name: 'cdp_hog_function_monitoring_pending_messages',
    help: 'Number of log entries queued and waiting to be flushed to Kafka. App-metric backlog is tracked separately by app_metrics_aggregator_queued_total / app_metrics_aggregator_flushed_total. High values indicate accumulation and potential memory leak.',
})

export type MonitoringOutput = AppMetricsOutput | LogEntriesOutput

// `app_metrics2` has no version column, and it can't gain one: it's an AggregatingMergeTree whose sort
// key is its aggregation key, so a new dimension would have to join the ORDER BY and re-key existing
// parts. Instead, every hog flow metric that knows its workflow version is written twice — once under
// `hog_flow` (the version-agnostic series everything already reads) and once under this app source with
// the version appended to the flow id. Same instance_id/kind/name semantics on both, so a
// version-scoped read is the existing query with two substituted parameters.
export const HOG_FLOW_VERSION_APP_SOURCE = 'hog_flow_version'

// This key format is the contract for anything that reads the versioned series — see
// "Metrics and version attribution" in products/workflows/CONTRIBUTING.md. Always the flow id, never
// the run id the version-agnostic series uses for batch runs.
export const versionedAppSourceId = (flowId: string, version: number): string => `${flowId}/${version}`

// Check if the result is of type CyclotronJobInvocationHogFunction
export const isHogFunctionResult = (
    result: CyclotronJobInvocationResult
): result is CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction> => {
    return 'hogFunction' in result.invocation
}

export const isHogFlowResult = (
    result: CyclotronJobInvocationResult
): result is CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow> => {
    return 'hogFlow' in result.invocation
}

export class HogFunctionMonitoringService {
    queuedLogMessages: LogEntrySerialized[] = []

    private appMetricsAggregator: AppMetricsAggregator

    constructor(private outputs: IngestionOutputs<MonitoringOutput>) {
        this.appMetricsAggregator = new AppMetricsAggregator(outputs)
    }

    async flush() {
        const messages = [...this.queuedLogMessages]
        this.queuedLogMessages = []
        hogFunctionMonitoringPendingMessages.set(0)

        await Promise.all([
            this.appMetricsAggregator.flush().catch((error) => {
                // Best-effort — don't disrupt processing just for metrics.
                logger.error('⚠️', `failed to flush app metrics: ${error}`, { error: String(error) })
                captureException(error)
            }),
            ...messages.map((x) => {
                const value = x ? Buffer.from(safeClickhouseString(JSON.stringify(x))) : null
                return this.outputs
                    .produce(LOG_ENTRIES_OUTPUT, {
                        key: null,
                        value,
                    })
                    .catch((error) => {
                        // NOTE: We don't hard fail here - this is because we don't want to disrupt the
                        // entire processing just for metrics.
                        logger.error('⚠️', `failed to produce log entry: ${error}`, {
                            error: String(error),
                            messageLength: value?.length,
                        })

                        captureException(error)
                    })
            }),
        ])
    }

    queueAppMetric(metric: MinimalAppMetric, source: MetricLogSource) {
        counterHogFunctionMetric.labels(metric.metric_kind, metric.metric_name).inc(metric.count)

        this.appMetricsAggregator.queue({
            team_id: metric.team_id,
            app_source: source,
            app_source_id: metric.app_source_id,
            instance_id: metric.instance_id,
            metric_kind: metric.metric_kind,
            metric_name: metric.metric_name,
            count: metric.count,
        })

        // Guarded on the type rather than truthiness: a flow loaded without its `version` column would
        // otherwise key every mirrored row under a literal `.../undefined`.
        if (source === 'hog_flow' && typeof metric.app_source_version?.version === 'number') {
            this.appMetricsAggregator.queue({
                team_id: metric.team_id,
                app_source: HOG_FLOW_VERSION_APP_SOURCE,
                // Deliberately not `metric.app_source_id` — see `app_source_version` on MinimalAppMetric.
                app_source_id: versionedAppSourceId(metric.app_source_version.id, metric.app_source_version.version),
                instance_id: metric.instance_id,
                metric_kind: metric.metric_kind,
                metric_name: metric.metric_name,
                count: metric.count,
            })
        }
    }

    queueAppMetrics(metrics: MinimalAppMetric[], source: MetricLogSource) {
        metrics.forEach((metric) => this.queueAppMetric(metric, source))
    }

    queueLogs(logEntries: LogEntry[], source: MetricLogSource) {
        const logs = fixLogDeduplication(
            logEntries.map((logEntry) => ({
                ...logEntry,
                log_source: source,
            }))
        )

        logs.forEach((logEntry) => {
            this.queuedLogMessages.push(logEntry)
        })
        hogFunctionMonitoringPendingMessages.set(this.queuedLogMessages.length)
    }

    queueInvocationResults(results: CyclotronJobInvocationResult[]): void {
        for (const result of results) {
            const source = 'hogFunction' in result.invocation ? 'hog_function' : 'hog_flow'
            const logSourceId = result.invocation.parentRunId
                ? result.invocation.parentRunId
                : result.invocation.functionId
            // Stamped here rather than at each of the ~10 sites that push onto `result.metrics`
            // (executor, action handlers, billing). The workflow is re-read from the manager on every
            // dequeue, so this is the version that actually executed the step — a run started on v2
            // that reaches its email step after v3 is published attributes that step to v3.
            const appSourceVersion = isHogFlowResult(result)
                ? { id: result.invocation.hogFlow.id, version: result.invocation.hogFlow.version }
                : undefined

            this.queueLogs(
                result.logs.map((logEntry) => ({
                    ...logEntry,
                    team_id: result.invocation.teamId,
                    log_source: source,
                    log_source_id: logSourceId,
                    instance_id: result.invocation.id,
                })),
                source
            )

            if (result.metrics) {
                this.queueAppMetrics(
                    appSourceVersion !== undefined
                        ? result.metrics.map((metric) => ({ app_source_version: appSourceVersion, ...metric }))
                        : result.metrics,
                    source
                )
            }

            // A canceled run is neither a success nor a failure: it carries its own
            // 'canceled' metric on result.metrics, so the derived terminal metric is skipped.
            if ((result.finished || result.error) && !result.canceled) {
                // Process each timing entry individually instead of totaling them
                const timings = isHogFunctionResult(result) ? (result.invocation.state?.timings ?? []) : []
                for (const timing of timings) {
                    // Record metrics for this timing entry
                    hogFunctionExecutionTimeSummary.labels({ kind: timing.kind }).observe(timing.duration_ms)
                }

                this.queueAppMetric(
                    {
                        team_id: result.invocation.teamId,
                        app_source_id: result.invocation.parentRunId ?? result.invocation.functionId,
                        metric_kind: result.error ? 'failure' : 'success',
                        metric_name: result.error ? 'failed' : 'succeeded',
                        count: 1,
                        app_source_version: appSourceVersion,
                    },
                    source
                )
            }
        }
    }
}
