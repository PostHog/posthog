import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'

import { parseKafkaHeaders } from '~/common/kafka/consumer'
import { retryOnDependencyUnavailableError } from '~/common/kafka/error-handling'
import { AppMetricsAggregator } from '~/common/services/app-metrics-aggregator'
import { QuotaResource } from '~/common/services/quota-limiting.service'
import { logger } from '~/common/utils/logger'
import type { LogsSettings } from '~/types'

import { recordLogMessageDlq } from '../ingestion-otel-metrics'
import type { InternalLogsVerifier } from '../internal-logs'
import { logMessageDlqCounter, teamIdMatchesCsv } from '../logs-ingestion-consumer'
import type { LogsIngestionConsumerDeps } from '../logs-ingestion-consumer'
import type { MetricRuleSource } from '../metrics-rules/compile-metric-rules'
import type { MetricSeriesAdmission } from '../metrics-rules/tally'
import { LOGS_DLQ_OUTPUT } from '../outputs/outputs'
import type { RetentionRuleSource } from '../retention/compile-retention-rules'
import { RETENTION_MONTH_DAYS } from '../retention/evaluate-retention'
import type { LogsSamplingService } from '../sampling/logs-sampling.service'
import type { SamplingRuleSource } from '../sampling/sampling-rules-cache'
import type { LogsRateLimiterService } from '../services/logs-rate-limiter.service'
import type { LogsIngestionMessage } from '../types'

export { teamIdMatchesCsv }

/** Traces bill against the logs quota bucket, and both rule sources use the record vocabulary (`spans`), not `traces`. */
export type LogsConsumerIdentity = {
    name: string
    appSource: 'logs' | 'traces'
    quotaResource: QuotaResource
    metricRuleSource: MetricRuleSource
    retentionRuleSource: RetentionRuleSource
    samplingRuleSource: SamplingRuleSource
}

export type LogsFeatureGates = {
    backfillEnabledTeams: string
    samplingEnabledTeams: string
    samplingKillswitch: boolean
    billingProrateEnabled: boolean
    metricRulesEnabledTeams: string
    metricRulesKillswitch: boolean
    defaultMetricRulesEnabledTeams: string
    transformationsEnabledTeams: string
    transformationsKillswitch: boolean
    retentionEnabledTeams: string
    retentionKillswitch: boolean
    patternMaskingEnabledTeams: string
    jsonAttributeParsingEnabledTeams: string
    jsonAttributeExtractionEnabledTeams: string
}

/** Lives as long as the consumer, so rows a failed batch queued flush with the next good batch, as billing relies on. */
export class LogsUsageMetricsQueue {
    constructor(
        private readonly aggregator: AppMetricsAggregator,
        private readonly appSource: string
    ) {}

    queueUsageMetric(teamId: number, metricName: string, count: number, timestamp?: DateTime): void {
        if (count === 0) {
            return
        }
        this.aggregator.queue({
            team_id: teamId,
            app_source: this.appSource,
            app_source_id: '',
            instance_id: '',
            metric_kind: 'usage',
            metric_name: metricName,
            count,
            timestamp,
        })
    }

    /** One row per 30-day month, dated at its start, so each month bills when it begins and the TTL keeps future rows until billed. */
    queueRetentionByteDays(teamId: number, bytes: number, retentionDays: number): void {
        const now = DateTime.utc()
        for (let offsetDays = 0; offsetDays < retentionDays; offsetDays += RETENTION_MONTH_DAYS) {
            const days = Math.min(RETENTION_MONTH_DAYS, retentionDays - offsetDays)
            this.queueUsageMetric(teamId, 'retention_byte_days', bytes * days, now.plus({ days: offsetDays }))
        }
    }

    queueByRule(teamId: number, metricName: string, byRule: Map<string, number>): void {
        for (const [ruleId, count] of byRule) {
            if (count <= 0) {
                continue
            }
            this.aggregator.queue({
                team_id: teamId,
                app_source: this.appSource,
                app_source_id: '',
                instance_id: ruleId,
                metric_kind: 'usage',
                metric_name: metricName,
                count,
            })
        }
    }

    flush(): Promise<void> {
        return this.aggregator.flush()
    }
}

export type LogsPipelineContext = {
    identity: LogsConsumerIdentity
    gates: LogsFeatureGates
    deps: LogsIngestionConsumerDeps
    usageMetrics: LogsUsageMetricsQueue
    rateLimiter: Pick<LogsRateLimiterService, 'filterMessages'>
    samplingService: LogsSamplingService
    internalLogsVerifier: InternalLogsVerifier
    metricSeriesAdmission: MetricSeriesAdmission
    defaultRetentionDays: (teamId: number, logsSettings: LogsSettings) => Promise<number>
}

/** Transformations write hog_function logs, which could come back here as internal logs and loop. */
export function appliesTeamLogRules(message: LogsIngestionMessage): boolean {
    return message.verifiedAsInternalLogs?.teamRules ?? true
}

export function isUnbilledInternal(message: LogsIngestionMessage): boolean {
    return message.verifiedAsInternalLogs !== undefined && !message.verifiedAsInternalLogs.billed
}

/** A failed batch replays in full and the logs table has no dedupe, so each retry here avoids duplicates. */
export function retryOnDependencyUnavailable<T>(context: LogsPipelineContext, fn: () => Promise<T>): Promise<T> {
    return retryOnDependencyUnavailableError(fn, context.deps.dependencyRetry)
}

/** The DLQ headers are the replay contract, and a failed write rejects so the offset never commits without a copy. */
export async function quarantineLogMessage(
    context: LogsPipelineContext,
    message: Message,
    error: unknown,
    owner: { token?: string; teamId?: number }
): Promise<void> {
    const errorMessage = error instanceof Error ? error.message : String(error)
    const errorName = error instanceof Error ? error.name : 'UnknownError'
    const teamIdLabel = owner.teamId?.toString() ?? 'unknown'

    logMessageDlqCounter.inc({ reason: errorName, team_id: teamIdLabel })
    recordLogMessageDlq(errorName, teamIdLabel)

    try {
        await retryOnDependencyUnavailable(context, () =>
            context.deps.outputs.queueMessages(LOGS_DLQ_OUTPUT, [
                {
                    value: message.value,
                    key: null,
                    headers: {
                        ...parseKafkaHeaders(message.headers),
                        ...(owner.token !== undefined ? { token: owner.token } : {}),
                        team_id: teamIdLabel,
                        error_message: errorMessage,
                        error_name: errorName,
                        failed_at: new Date().toISOString(),
                        source_topic: message.topic,
                        source_partition: message.partition.toString(),
                        source_offset: message.offset.toString(),
                    },
                },
            ])
        )
    } catch (dlqError) {
        logger.error('Failed to produce message to DLQ', {
            error: dlqError,
            originalError: errorMessage,
            partition: message.partition,
            offset: message.offset,
        })
        throw dlqError
    }
}
