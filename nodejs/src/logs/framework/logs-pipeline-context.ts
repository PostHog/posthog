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
import type { LogsRateLimiterService } from '../services/logs-rate-limiter.service'
import type { LogsIngestionMessage } from '../types'

export { teamIdMatchesCsv }

/**
 * What differs between the logs and traces consumers. Traces bill against the logs quota bucket, so
 * `quotaResource` is the same for both. The two rule sources use the record vocabulary (`spans`),
 * not the billing vocabulary (`traces`).
 */
export type LogsConsumerIdentity = {
    name: string
    appSource: 'logs' | 'traces'
    quotaResource: QuotaResource
    metricRuleSource: MetricRuleSource
    retentionRuleSource: RetentionRuleSource
}

/** Feature gates read once from the merged consumer config. */
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

/**
 * Queues app_metrics2 usage rows. One instance lives as long as the consumer: rows that a failed
 * batch queued are flushed with the next batch that succeeds, which is the behavior billing relies on.
 */
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

    /**
     * Writes one `retention_byte_days` row per 30-day month of retention, each dated at the start of
     * its month, so each month of storage bills when it starts instead of the whole period billing
     * on the ingest day. The usage report sums these rows by timestamp, and the `app_metrics2` TTL
     * counts from each row's own timestamp, so future rows stay until they are billed.
     */
    queueRetentionByteDays(teamId: number, bytes: number, retentionDays: number): void {
        const now = DateTime.utc()
        for (let offsetDays = 0; offsetDays < retentionDays; offsetDays += RETENTION_MONTH_DAYS) {
            const days = Math.min(RETENTION_MONTH_DAYS, retentionDays - offsetDays)
            this.queueUsageMetric(teamId, 'retention_byte_days', bytes * days, now.plus({ days: offsetDays }))
        }
    }

    /**
     * Per-rule counts in app_metrics2, keyed by rule id in `instance_id`. Used for
     * `sampling_records_dropped_by_rule` (team sampling volume is `sum(count)` over those rows) and
     * `bytes_dropped_by_rule` (summed from per-row `bytes_uncompressed`).
     */
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

/**
 * Long-lived services and settings that the logs pipeline steps share. The consumer builds one
 * instance at construction; each step factory closes over the parts it needs.
 */
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
    return message.internalLogs?.teamRules ?? true
}

export function isUnbilledInternal(message: LogsIngestionMessage): boolean {
    return message.internalLogs !== undefined && !message.internalLogs.billed
}

/**
 * Absorb a dependency blip in place. A batch that fails after some of its messages were
 * produced is replayed in full, and the logs table has no dedupe, so every retry here is a
 * duplicate avoided. Only an outage that outlasts the backoff reaches the caller.
 */
export function retryOnDependencyUnavailable<T>(context: LogsPipelineContext, fn: () => Promise<T>): Promise<T> {
    return retryOnDependencyUnavailableError(fn, context.deps.dependencyRetry)
}

/**
 * Quarantine a raw Kafka message. Takes the message rather than a `LogsIngestionMessage` so
 * failures from before the team is resolved can reach the DLQ too. The DLQ headers are the replay
 * contract, which is why this does not use the framework's generic DLQ output.
 *
 * A failed DLQ write rejects: quarantine is what lets the batch move past the record, and
 * swallowing the failure would commit the source offset with no copy anywhere.
 */
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
                        // Where the message came from, so a quarantined record can be read back
                        // from the source partition and replayed against the consumer.
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
