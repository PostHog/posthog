import { logger } from '~/common/utils/logger'
import { UUID7 } from '~/common/utils/utils'

import { recordInternalLogs } from '../ingestion-otel-metrics'
import {
    DEFAULT_LOGS_RETENTION_DAYS,
    UsageStatsByTeam,
    logsInternalBytesCounter,
    logsInternalRecordsCounter,
    logsMetricRulesEvalErrorCounter,
    logsMetricRulesRecordsMatchedCounter,
    logsMetricRulesSeriesOverflowCounter,
    logsMetricRulesValueSkippedCounter,
    retentionBytesMetricName,
} from '../logs-ingestion-consumer'
import { buildMetricRulesOtlpPayload } from '../metrics-rules/otlp-payload'
import type { LogsIngestionMessage } from '../types'
import { LogsPipelineContext } from './logs-pipeline-context'
import type { MetricTalliesByTeam } from './process-log-message-step'

/** The usage report matches `bytes_ingested` exactly, so these names never reach billing. */
export function queueInternalLogsUsage(context: LogsPipelineContext, internalMessages: LogsIngestionMessage[]): void {
    for (const message of internalMessages) {
        context.usageMetrics.queueUsageMetric(message.teamId, 'bytes_ingested_internal', message.bytesUncompressed)
        context.usageMetrics.queueUsageMetric(message.teamId, 'records_ingested_internal', message.recordCount)
        const teamId = message.teamId.toString()
        logsInternalBytesCounter.inc({ team_id: teamId }, message.bytesUncompressed)
        logsInternalRecordsCounter.inc({ team_id: teamId }, message.recordCount)
        recordInternalLogs(message.teamId, message.bytesUncompressed, message.recordCount)
    }
}

/** One OTLP payload per team. Emission is best effort and never fails log ingestion. */
export async function emitMetricRuleTallies(context: LogsPipelineContext, byTeam: MetricTalliesByTeam): Promise<void> {
    for (const [teamId, { token, rules, tallies }] of byTeam) {
        const teamIdLabel = teamId.toString()
        if (tallies.valueSkipped > 0) {
            logsMetricRulesValueSkippedCounter.inc({ team_id: teamIdLabel }, tallies.valueSkipped)
        }
        if (tallies.evalErrors > 0) {
            logsMetricRulesEvalErrorCounter.inc({ team_id: teamIdLabel }, tallies.evalErrors)
        }
        let overflow = 0
        for (const count of tallies.seriesOverflow.values()) {
            overflow += count
        }
        if (overflow > 0) {
            logsMetricRulesSeriesOverflowCounter.inc({ team_id: teamIdLabel }, overflow)
        }
        let matched = 0
        for (const ruleTallies of tallies.byRule.values()) {
            for (const entry of ruleTallies.values()) {
                matched += entry.count
            }
        }
        if (matched > 0) {
            logsMetricRulesRecordsMatchedCounter.inc({ team_id: teamIdLabel }, matched)
        }

        const payload = buildMetricRulesOtlpPayload(rules, tallies, Date.now())
        if (!payload) {
            continue
        }
        try {
            await context.deps.metricsEmitter!.emit(token, teamId, payload)
        } catch (error) {
            logger.warn('[logs-metric-rules] emit threw', { teamId, error: String(error) })
        }
    }
}

/**
 * Queues the batch's usage rows and flushes every queued app metric and usage record. Both flushes
 * are best effort and independent: neither failing may block ingestion or skip the other.
 */
export async function emitUsageMetrics(context: LogsPipelineContext, usageStats: UsageStatsByTeam): Promise<void> {
    const { usageMetrics, identity, deps } = context
    for (const [teamId, stats] of usageStats) {
        usageMetrics.queueUsageMetric(teamId, 'bytes_received', stats.bytesReceived)
        usageMetrics.queueUsageMetric(teamId, 'records_received', stats.recordsReceived)
        usageMetrics.queueUsageMetric(teamId, 'bytes_ingested', stats.bytesAllowed)
        // Records-based counterpart to `bytes_ingested`, emitted in parallel so the two can be
        // compared before billing switches to it; not yet read by usage reports.
        usageMetrics.queueUsageMetric(teamId, 'bytes_ingested_records', stats.bytesAllowedRecords)
        usageMetrics.queueUsageMetric(teamId, 'records_ingested', stats.recordsAllowed)
        usageMetrics.queueUsageMetric(teamId, 'bytes_dropped', stats.bytesDropped)
        usageMetrics.queueUsageMetric(teamId, 'records_dropped', stats.recordsDropped)
        usageMetrics.queueUsageMetric(teamId, 'pii_replacements', stats.piiReplacements)

        const retentionMetric = retentionBytesMetricName(stats.retentionDays)
        if (retentionMetric) {
            usageMetrics.queueUsageMetric(teamId, retentionMetric, stats.bytesAllowed)
        }
        // Byte-days only for teams that chose a retention other than the default, which
        // `bytes_ingested` already covers. Uses credit-adjusted `bytesAllowed` to reconcile with it.
        if (stats.retentionDays !== DEFAULT_LOGS_RETENTION_DAYS) {
            usageMetrics.queueRetentionByteDays(teamId, stats.bytesAllowed, stats.retentionDays)
        }
        const source = identity.appSource === 'traces' ? 'apm_traces' : 'logs'
        // Per-flush aggregates have no stable identity. A fresh ID per flush keeps two pods
        // flushing the same team from colliding and collapsing one flush's quantity away.
        const flushId = new UUID7().toString()
        deps.usageBatch.add(teamId, `${source}_bytes`, flushId, stats.bytesAllowed, 'bytes')
        deps.usageBatch.add(
            teamId,
            source === 'apm_traces' ? 'apm_traces_spans' : 'logs_records',
            flushId,
            stats.recordsAllowed,
            'records'
        )
    }

    await Promise.all([
        usageMetrics.flush().catch((error) => {
            logger.error('🔴', 'Failed to emit usage metrics - billing data may be lost', { error })
        }),
        deps.usageBatch.flush().catch((error) => {
            logger.error('🔴', 'Failed to emit usage records - billing data may be lost', { error })
        }),
    ])
}
