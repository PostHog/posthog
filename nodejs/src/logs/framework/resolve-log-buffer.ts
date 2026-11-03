import { trace } from '@opentelemetry/api'

import type { LogsSettings } from '~/types'

import { MESSAGE_KEYS } from '../log-pattern-mask'
import { logsPatternForcedDecodeCounter, makePatternMaskingStage } from '../log-pattern-stage'
import { type PiiScrubStats } from '../log-pii-scrub'
import {
    type LogRecord,
    type LogRecordsTransform,
    bufferProcessingMode,
    processLogMessageBuffer,
} from '../log-record-avro'
import {
    INTERNAL_LOGS_MIN_RETENTION_DAYS,
    logsBytesDroppedByRuleCounter,
    logsSamplingRecordsDroppedCounter,
    makeTransformStage,
} from '../logs-ingestion-consumer'
import { type PipelineStage } from '../pipeline/log-processing-pipeline'
import { type CompiledRetentionRuleSet } from '../retention/evaluate-retention'
import { canHoldExpiredRow, makeRetentionExpiredStage } from '../retention/retention-expired-stage'
import { makeRetentionStage } from '../retention/retention-stage'
import type { CompiledRuleSet } from '../sampling/evaluate'
import { SAMPLING_STAGE_NAME } from '../sampling/logs-sampling.service'
import type { TransformationBatchBudget } from '../transformations/logs-transformer.service'
import type { LogsIngestionMessage } from '../types'
import {
    LogsPipelineContext,
    appliesTeamLogRules,
    retryOnDependencyUnavailable,
    teamIdMatchesCsv,
} from './logs-pipeline-context'

type ResolvedDrops = {
    pii: PiiScrubStats
    recordsDropped: number
    recordsDroppedByStage: Map<string, number>
    recordsDroppedByRuleId: Map<string, number>
    bytesDroppedByRuleId: Map<string, number>
    contentBytesDropped: number
    contentBytesTotal: number
}

export type ResolvedLogBuffer =
    | ({ outcome: 'produce'; processedValue: Buffer } & ResolvedDrops)
    | ({ outcome: 'all_dropped'; reason: string } & ResolvedDrops)

function isSamplingEvalEnabledForTeam(context: LogsPipelineContext, teamId: number): boolean {
    return !context.gates.samplingKillswitch && teamIdMatchesCsv(context.gates.samplingEnabledTeams, teamId)
}

export function isRetentionEvalEnabledForTeam(context: LogsPipelineContext, teamId: number): boolean {
    return !context.gates.retentionKillswitch && teamIdMatchesCsv(context.gates.retentionEnabledTeams, teamId)
}

function isTransformationsEnabledForTeam(context: LogsPipelineContext, teamId: number): boolean {
    if (context.gates.transformationsKillswitch || !context.deps.logsTransformer) {
        return false
    }
    return teamIdMatchesCsv(context.gates.transformationsEnabledTeams, teamId)
}

/** Logs only, because a trace record has no `body` field and would skew the log-body metrics. */
export function isPatternMaskingEnabledForTeam(context: LogsPipelineContext, teamId: number): boolean {
    return context.identity.appSource === 'logs' && teamIdMatchesCsv(context.gates.patternMaskingEnabledTeams, teamId)
}

async function buildRecordsTransform(
    context: LogsPipelineContext,
    message: LogsIngestionMessage,
    batchBudget?: TransformationBatchBudget
): Promise<LogRecordsTransform | undefined> {
    const transformer = context.deps.logsTransformer
    if (!transformer || !appliesTeamLogRules(message) || !isTransformationsEnabledForTeam(context, message.teamId)) {
        return undefined
    }
    if (!(await transformer.teamHasTransformations(message.teamId))) {
        return undefined
    }
    return (records) => transformer.transformRecords(message.teamId, records, batchBudget)
}

export async function resolveLogBuffer(
    context: LogsPipelineContext,
    message: LogsIngestionMessage,
    logsSettings: LogsSettings,
    defaultRetentionDays: number,
    onRecordsDecoded?: (records: LogRecord[]) => void,
    batchBudget?: TransformationBatchBudget
): Promise<ResolvedLogBuffer> {
    const { deps, gates } = context
    const samplingCache = deps.samplingRulesCache
    const samplingEvalEnabled = isSamplingEvalEnabledForTeam(context, message.teamId)
    let ruleSet: CompiledRuleSet | null = null
    if (samplingCache && samplingEvalEnabled && appliesTeamLogRules(message)) {
        ruleSet = await samplingCache.getCompiledRuleSet(message.teamId)
    }
    const useSamplingPipeline = Boolean(ruleSet && ruleSet.rules.length > 0)
    const recordsTransform = await buildRecordsTransform(context, message, batchBudget)

    // With no rules, the batch `retention-days` header carries the team default and the buffer skips the decode.
    const retentionCache = deps.retentionRulesCache
    const retentionEvalEnabled = isRetentionEvalEnabledForTeam(context, message.teamId)
    let retentionRuleSet: CompiledRetentionRuleSet | null = null
    if (retentionCache && retentionEvalEnabled && appliesTeamLogRules(message)) {
        retentionRuleSet = await retentionCache.getCompiledRuleSet(message.teamId, context.identity.retentionRuleSource)
    }
    const useRetention = Boolean(retentionRuleSet && retentionRuleSet.rules.length > 0)

    // Retention stamping runs after sampling and transformations, so it only stamps survivors.
    const stages: PipelineStage[] = []
    if (useSamplingPipeline && ruleSet) {
        stages.push(context.samplingService.makeSamplingStage(ruleSet, message.teamId, message.bytesUncompressed))
    }
    if (recordsTransform) {
        stages.push(makeTransformStage(recordsTransform))
    }
    let shortestRetentionDays =
        message.internalLogs !== undefined ? INTERNAL_LOGS_MIN_RETENTION_DAYS : defaultRetentionDays
    if (useRetention && retentionRuleSet) {
        stages.push(makeRetentionStage(retentionRuleSet, message.teamId, defaultRetentionDays))
        shortestRetentionDays = Math.min(
            defaultRetentionDays,
            ...retentionRuleSet.rules.map((rule) => rule.retentionDays)
        )
    }

    // Only a message that can hold an expired row pays the decode. The stage runs after retention to read the per-row value.
    const nowMicros = Date.now() * 1000
    if (canHoldExpiredRow(message.minTimestampMicros, shortestRetentionDays, nowMicros)) {
        stages.push(makeRetentionExpiredStage(message.teamId, defaultRetentionDays, nowMicros))
    }

    // Masking runs last and forces a full decode and re-encode, so the counter prices each forced decode.
    if (isPatternMaskingEnabledForTeam(context, message.teamId)) {
        const modeWithoutMasking = bufferProcessingMode(logsSettings, stages.length, Boolean(onRecordsDecoded))
        if (modeWithoutMasking !== 'decode_and_reencode') {
            logsPatternForcedDecodeCounter.inc({ from: modeWithoutMasking })
        }
        const keysCache = deps.patternMessageKeysCache
        const messageKeys = keysCache
            ? await retryOnDependencyUnavailable(context, () => keysCache.getMessageKeys(message.teamId))
            : MESSAGE_KEYS
        stages.push(makePatternMaskingStage(messageKeys))
    }

    trace.getActiveSpan()?.setAttributes({
        'logs.sampling.killswitch': gates.samplingKillswitch,
        'logs.sampling.enabled_teams_configured': Boolean((gates.samplingEnabledTeams || '').trim()),
        'logs.sampling.enabled_teams_is_wildcard': (gates.samplingEnabledTeams || '').trim() === '*',
        'logs.sampling.cache_present': Boolean(samplingCache),
        'logs.sampling.eval_enabled_for_team': samplingEvalEnabled,
        'logs.sampling.compiled_rule_count': ruleSet?.rules.length ?? 0,
        'logs.transformations.enabled_for_team': Boolean(recordsTransform),
        'logs.retention.cache_present': Boolean(retentionCache),
        'logs.retention.eval_enabled_for_team': retentionEvalEnabled,
        'logs.retention.compiled_rule_count': retentionRuleSet?.rules.length ?? 0,
        'logs.retention.use_retention': useRetention,
        'logs.sampling.pipeline': useSamplingPipeline
            ? 'decode_sample_encode'
            : recordsTransform
              ? 'decode_transform_encode'
              : 'passthrough',
    })

    const { value, pii, drops } = await processLogMessageBuffer(message.message.value!, logsSettings, {
        onRecordsDecoded,
        stages,
    })

    const recordsDroppedBySampling = drops.recordsDroppedByStage.get(SAMPLING_STAGE_NAME) ?? 0
    if (recordsDroppedBySampling > 0) {
        logsSamplingRecordsDroppedCounter.inc({ team_id: message.teamId.toString() }, recordsDroppedBySampling)
    }
    if (drops.bytesDropped > 0) {
        logsBytesDroppedByRuleCounter.inc({ team_id: message.teamId.toString() }, drops.bytesDropped)
    }

    const resolvedDrops: ResolvedDrops = {
        pii,
        recordsDropped: drops.recordsDropped,
        recordsDroppedByStage: drops.recordsDroppedByStage,
        recordsDroppedByRuleId: drops.recordsDroppedByRuleId,
        bytesDroppedByRuleId: drops.bytesDroppedByRuleId,
        contentBytesDropped: drops.contentBytesDropped,
        contentBytesTotal: drops.contentBytesTotal,
    }
    if (value === null) {
        const reason = drops.droppedBy ? `${drops.droppedBy}_all_dropped` : 'empty_batch'
        return { outcome: 'all_dropped', reason, ...resolvedDrops }
    }
    return { outcome: 'produce', processedValue: value, ...resolvedDrops }
}
