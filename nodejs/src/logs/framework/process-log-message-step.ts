import { parseKafkaHeaders } from '~/common/kafka/consumer'
import { recordPiiReplacements } from '~/common/metrics/otel-metrics'
import { instrumentFn } from '~/common/tracing/tracing-utils'
import { DependencyUnavailableError } from '~/common/utils/db/error'
import { logger } from '~/common/utils/logger'
import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'

import { recordLogMessageDropped } from '../ingestion-otel-metrics'
import { INTERNAL_SOURCE_HEADER, withoutInternalLogsHeaders } from '../internal-logs'
import { type PiiScrubStats } from '../log-pii-scrub'
import { type LogRecord, sniffJsonLogAttributes } from '../log-record-avro'
import {
    DEFAULT_USAGE_STATS,
    UsageStatsByTeam,
    billingByteReductionForDrops,
    logMessageDroppedCounter,
    logsBillingBytesCreditedCounter,
    logsBillingProrateDivergenceHistogram,
    logsBillingRecordsCreditedCounter,
    logsDropBatchRowsHistogram,
    logsDropFractionHistogram,
} from '../logs-ingestion-consumer'
import { rethrowKafkaOutageAsDependency } from '../logs-produce-errors'
import type { CompiledMetricRule } from '../metrics-rules/compile-metric-rules'
import { withDefaultMetricRules } from '../metrics-rules/default-metric-rules'
import { type BatchTallies, createBatchTallies, tallyRecords } from '../metrics-rules/tally'
import { LOGS_OUTPUT } from '../outputs/outputs'
import { RETENTION_EXPIRED_STAGE_NAME } from '../retention/retention-expired-stage'
import type { TransformationBatchBudget } from '../transformations/logs-transformer.service'
import type { LogsIngestionMessage } from '../types'
import {
    LogsPipelineContext,
    appliesTeamLogRules,
    isUnbilledInternal,
    quarantineLogMessage,
    retryOnDependencyUnavailable,
    teamIdMatchesCsv,
} from './logs-pipeline-context'
import { resolveLogBuffer } from './resolve-log-buffer'

export type MetricRuleBatchState = { token: string; rules: CompiledMetricRule[]; tallies: BatchTallies }
export type MetricTalliesByTeam = Map<number, MetricRuleBatchState>

export type LogsProcessingPass = {
    usage: UsageStatsByTeam
    metricTallies: MetricTalliesByTeam
    transformationBudget?: TransformationBatchBudget
}

export type LogsProcessingInput = LogsIngestionMessage & { pass: LogsProcessingPass }

/** A message never fails its pass on its own: `failure` fails the pass once every message has settled. */
export type LogsProcessingOutcome = LogsProcessingInput & { quarantined: boolean; failure?: unknown }

function canEmitMetricRules(context: LogsPipelineContext): boolean {
    return !context.gates.metricRulesKillswitch && !!context.deps.metricRulesCache && !!context.deps.metricsEmitter
}

async function getMetricRuleBatchState(
    context: LogsPipelineContext,
    byTeam: MetricTalliesByTeam,
    message: LogsIngestionMessage
): Promise<MetricRuleBatchState | null> {
    if (!appliesTeamLogRules(message)) {
        return null
    }
    const teamRulesEnabled =
        canEmitMetricRules(context) && teamIdMatchesCsv(context.gates.metricRulesEnabledTeams, message.teamId)
    const defaultRulesEnabled =
        canEmitMetricRules(context) && teamIdMatchesCsv(context.gates.defaultMetricRulesEnabledTeams, message.teamId)
    if (!teamRulesEnabled && !defaultRulesEnabled) {
        return null
    }
    let state = byTeam.get(message.teamId)
    if (!state) {
        let rules: CompiledMetricRule[] = []
        try {
            if (teamRulesEnabled) {
                const all = await context.deps.metricRulesCache!.getCompiledRules(message.teamId)
                rules = all.filter((r) => r.source === context.identity.metricRuleSource)
            }
        } catch (error) {
            // Fail open, because metric rules are additive and a rules-fetch failure must never DLQ or block the log records.
            logger.warn('[logs-metric-rules] rules fetch failed — skipping metric rules for batch', {
                teamId: message.teamId,
                error: String(error),
            })
            return null
        }
        if (defaultRulesEnabled) {
            rules = withDefaultMetricRules(rules, context.identity.metricRuleSource)
        }
        // Re-check after the await, because replacing a concurrent message's state drops its accumulated tallies.
        state = byTeam.get(message.teamId)
        if (!state) {
            state = { token: message.token, rules, tallies: createBatchTallies() }
            byTeam.set(message.teamId, state)
        }
    }
    return state.rules.length > 0 ? state : null
}

function addPiiStatsIntoUsage(
    context: LogsPipelineContext,
    usage: UsageStatsByTeam,
    teamId: number,
    delta: PiiScrubStats
): void {
    if (delta.piiReplacements === 0) {
        return
    }
    recordPiiReplacements(context.identity.appSource, delta.piiReplacements)
    const row = usage.get(teamId) || { ...DEFAULT_USAGE_STATS }
    row.piiReplacements += delta.piiReplacements
    usage.set(teamId, row)
}

type HeaderOverrides = { bytesUncompressed?: number; bytesCompressed?: number; recordCount?: number }

async function processLogMessage(context: LogsPipelineContext, input: LogsProcessingInput): Promise<void> {
    const { deps, gates, identity, usageMetrics } = context
    const { pass } = input
    const team = await retryOnDependencyUnavailable(context, () => deps.teamManager.getTeam(input.teamId))
    const logsSettings = team?.logs_settings || {}
    const jsonParse = logsSettings.json_parse_logs ?? false
    const retentionDays = await retryOnDependencyUnavailable(context, () =>
        context.defaultRetentionDays(input.teamId, logsSettings)
    )

    const teamStats = pass.usage.get(input.teamId)
    if (teamStats) {
        teamStats.retentionDays = retentionDays
    }

    if (input.message.value === null) {
        return
    }

    const metricRuleState = await getMetricRuleBatchState(context, pass.metricTallies, input)
    const jsonAttributeKey =
        identity.appSource === 'logs' && teamIdMatchesCsv(gates.jsonAttributeParsingEnabledTeams, input.teamId)
            ? logsSettings.json_parse_logs_attribute_key
            : undefined
    const onRecordsDecoded =
        metricRuleState || jsonAttributeKey
            ? (records: LogRecord[]) => {
                  if (metricRuleState) {
                      const nowMs = Date.now()
                      tallyRecords(metricRuleState.rules, records, metricRuleState.tallies, nowMs, (ruleId, labelKey) =>
                          context.metricSeriesAdmission.admit(input.teamId, ruleId, labelKey, nowMs)
                      )
                  }
                  if (jsonAttributeKey) {
                      sniffJsonLogAttributes(records, jsonAttributeKey, input.teamId)
                  }
              }
            : undefined

    const resolved = await instrumentFn(
        {
            key: 'logsIngestion.sampling.resolveLogMessageBuffer',
            measureTime: false,
            sendException: false,
            getLoggingContext: () => ({ team_id: input.teamId, inbound_bytes: input.message.value?.length ?? 0 }),
        },
        async () =>
            resolveLogBuffer(
                context,
                input,
                {
                    ...logsSettings,
                    json_parse_logs_attribute_key:
                        identity.appSource === 'logs' &&
                        teamIdMatchesCsv(gates.jsonAttributeExtractionEnabledTeams, input.teamId)
                            ? logsSettings.json_parse_logs_attribute_key
                            : undefined,
                },
                retentionDays,
                onRecordsDecoded,
                pass.transformationBudget
            )
    )

    usageMetrics.queueUsageMetric(
        input.teamId,
        'records_dropped_retention_expired',
        resolved.recordsDroppedByStage.get(RETENTION_EXPIRED_STAGE_NAME) ?? 0
    )

    const overrides: HeaderOverrides = {}

    // `bytesReceived` stays gross, while `bytesAllowed` and `recordsAllowed` count only the rows that survive drop rules.
    if (resolved.recordsDropped > 0) {
        const header = input.bytesUncompressed
        const contentCredit = billingByteReductionForDrops(
            header,
            resolved.contentBytesDropped,
            resolved.contentBytesTotal
        )
        // A record-weighted credit that diverges from the content-weighted one shows a size-skewed batch.
        const recordCredit = billingByteReductionForDrops(header, resolved.recordsDropped, input.recordCount)

        if (!isUnbilledInternal(input)) {
            const teamIdLabel = input.teamId.toString()
            if (contentCredit > 0) {
                logsBillingBytesCreditedCounter.inc({ team_id: teamIdLabel }, contentCredit)
            }
            logsBillingRecordsCreditedCounter.inc({ team_id: teamIdLabel }, resolved.recordsDropped)
        }
        if (input.recordCount > 0) {
            logsDropBatchRowsHistogram.observe(input.recordCount)
        }
        if (resolved.contentBytesTotal > 0) {
            logsDropFractionHistogram.observe(Math.min(1, resolved.contentBytesDropped / resolved.contentBytesTotal))
        }
        if (header > 0) {
            logsBillingProrateDivergenceHistogram.observe(Math.abs(contentCredit - recordCredit) / header)
        }

        if (gates.billingProrateEnabled) {
            const billingRow = pass.usage.get(input.teamId)
            if (billingRow) {
                billingRow.bytesAllowed = Math.max(0, billingRow.bytesAllowed - contentCredit)
                billingRow.recordsAllowed = Math.max(0, billingRow.recordsAllowed - resolved.recordsDropped)
            }

            const compressedCredit = billingByteReductionForDrops(
                input.bytesCompressed,
                resolved.contentBytesDropped,
                resolved.contentBytesTotal
            )
            overrides.bytesUncompressed = Math.max(0, header - contentCredit)
            overrides.bytesCompressed = Math.max(0, input.bytesCompressed - compressedCredit)
            overrides.recordCount = Math.max(0, input.recordCount - resolved.recordsDropped)
        }
    }

    addPiiStatsIntoUsage(context, pass.usage, input.teamId, resolved.pii)
    usageMetrics.queueByRule(input.teamId, 'sampling_records_dropped_by_rule', resolved.recordsDroppedByRuleId)
    usageMetrics.queueByRule(input.teamId, 'bytes_dropped_by_rule', resolved.bytesDroppedByRuleId)

    if (resolved.outcome === 'all_dropped') {
        logMessageDroppedCounter.inc({ reason: resolved.reason, team_id: input.teamId.toString() }, 1)
        recordLogMessageDropped(resolved.reason, input.teamId.toString())
        return
    }

    await retryOnDependencyUnavailable(context, () =>
        deps.outputs
            .queueMessages(LOGS_OUTPUT, [
                {
                    value: resolved.processedValue,
                    key: null,
                    headers: {
                        ...withoutInternalLogsHeaders(parseKafkaHeaders(input.message.headers)),
                        ...(input.internalLogs !== undefined
                            ? { [INTERNAL_SOURCE_HEADER]: input.internalLogs.source }
                            : {}),
                        token: input.token,
                        team_id: input.teamId.toString(),
                        'json-parse': jsonParse.toString(),
                        'retention-days': retentionDays.toString(),
                        // Both topics use random partitioning, so the ingestion lag checkpoint needs the source partition.
                        source_topic: input.message.topic,
                        source_partition: input.message.partition.toString(),
                        ...(overrides.bytesUncompressed !== undefined
                            ? { bytes_uncompressed: overrides.bytesUncompressed.toString() }
                            : {}),
                        ...(overrides.bytesCompressed !== undefined
                            ? { bytes_compressed: overrides.bytesCompressed.toString() }
                            : {}),
                        ...(overrides.recordCount !== undefined
                            ? { record_count: overrides.recordCount.toString() }
                            : {}),
                    },
                },
            ])
            .catch(rethrowKafkaOutageAsDependency)
    )
}

export function createProcessLogMessageStep<T extends LogsProcessingInput>(
    context: LogsPipelineContext
): ProcessingStep<T, T & { quarantined: boolean; failure?: unknown }> {
    return async function processLogMessageStep(input) {
        try {
            await processLogMessage(context, input)
            return ok({ ...input, quarantined: false })
        } catch (error) {
            if (error instanceof DependencyUnavailableError) {
                return ok({ ...input, quarantined: false, failure: error })
            }
            try {
                // The DLQ copy records this failure, so the batch can commit past the message.
                await quarantineLogMessage(context, input.message, error, { token: input.token, teamId: input.teamId })
                return ok({ ...input, quarantined: true })
            } catch (dlqError) {
                return ok({ ...input, quarantined: false, failure: dlqError })
            }
        }
    }
}
