import { ChunkProcessingStep } from '~/ingestion/framework/base-chunk-pipeline'
import { PipelineResult, drop, ok } from '~/ingestion/framework/results'

import {
    recordLogMessageDropped,
    recordLogsAllowed,
    recordLogsDropped,
    recordLogsReceived,
} from '../ingestion-otel-metrics'
import {
    DEFAULT_USAGE_STATS,
    UsageStats,
    UsageStatsByTeam,
    logMessageDroppedCounter,
    logsBytesAllowedCounter,
    logsBytesAllowedRecordsCounter,
    logsBytesDroppedCounter,
    logsBytesReceivedCounter,
    logsRecordsAllowedCounter,
    logsRecordsDroppedCounter,
    logsRecordsReceivedCounter,
} from '../logs-ingestion-consumer'
import type { LogsIngestionMessage } from '../types'
import { LogsPipelineContext, isUnbilledInternal, teamIdMatchesCsv } from './logs-pipeline-context'

export class LogsBatchUsage {
    readonly byTeam: UsageStatsByTeam = new Map()

    private row(teamId: number): UsageStats {
        let stats = this.byTeam.get(teamId)
        if (!stats) {
            stats = { ...DEFAULT_USAGE_STATS }
            this.byTeam.set(teamId, stats)
        }
        return stats
    }

    recordAllowed(message: LogsIngestionMessage): void {
        const stats = this.row(message.teamId)
        stats.bytesReceived += message.bytesUncompressed
        stats.recordsReceived += message.recordCount
        stats.bytesAllowed += message.bytesUncompressed
        stats.recordsAllowed += message.recordCount
        stats.bytesAllowedRecords += message.bytesUncompressedRecords
    }

    recordDropped(message: LogsIngestionMessage): void {
        const stats = this.row(message.teamId)
        stats.bytesReceived += message.bytesUncompressed
        stats.recordsReceived += message.recordCount
        stats.bytesDropped += message.bytesUncompressed
        stats.recordsDropped += message.recordCount
    }
}

export type LogsAdmissionInput = LogsIngestionMessage & { usage: LogsBatchUsage }

function countMessagesDropped(reason: string, countByTeam: Map<number, number>): void {
    for (const [teamId, count] of countByTeam) {
        logMessageDroppedCounter.inc({ reason, team_id: teamId.toString() }, count)
        recordLogMessageDropped(reason, teamId.toString(), count)
    }
}

/** Verified internal logs are never quota or rate limited, so counting them would show as drops. */
export function createTrackIncomingTrafficStep<T extends LogsAdmissionInput>(): ChunkProcessingStep<T, T> {
    return function trackIncomingTrafficStep(values) {
        let bytes = 0
        let records = 0
        for (const value of values) {
            if (isUnbilledInternal(value)) {
                continue
            }
            bytes += value.bytesUncompressed
            records += value.recordCount
        }
        logsBytesReceivedCounter.inc(bytes)
        logsRecordsReceivedCounter.inc(records)
        recordLogsReceived(bytes, records)
        return Promise.resolve(values.map((value) => ok(value)))
    }
}

/** Clamping backfilled rows to the ingest time would write the import onto today, so the gate drops the whole message. */
export function createBackfillGateStep<T extends LogsAdmissionInput>(
    context: LogsPipelineContext
): ChunkProcessingStep<T, T> {
    return function backfillGateStep(values) {
        const droppedByTeam = new Map<number, { messages: number; records: number; billed: boolean }>()
        const results = values.map((value): PipelineResult<T> => {
            if (!value.backfillRequested || teamIdMatchesCsv(context.gates.backfillEnabledTeams, value.teamId)) {
                return ok(value)
            }
            const dropped = droppedByTeam.get(value.teamId) ?? { messages: 0, records: 0, billed: false }
            dropped.messages++
            if (!isUnbilledInternal(value)) {
                dropped.records += value.recordCount
                dropped.billed = true
                value.usage.recordDropped(value)
            }
            droppedByTeam.set(value.teamId, dropped)
            return drop('backfill_not_enabled')
        })

        for (const [teamId, dropped] of droppedByTeam) {
            logMessageDroppedCounter.inc(
                { reason: 'backfill_not_enabled', team_id: teamId.toString() },
                dropped.messages
            )
            recordLogMessageDropped('backfill_not_enabled', teamId.toString(), dropped.messages)
            if (dropped.billed) {
                context.usageMetrics.queueUsageMetric(teamId, 'records_dropped_backfill_not_enabled', dropped.records)
            }
        }
        return Promise.resolve(results)
    }
}

export function createQuotaLimitStep<T extends LogsAdmissionInput>(
    context: LogsPipelineContext
): ChunkProcessingStep<T, T> {
    return async function quotaLimitStep(values) {
        const billed = values.filter((value) => !isUnbilledInternal(value))
        const uniqueTokens = [...new Set(billed.map((value) => value.token))]
        const limited = new Set(
            (
                await Promise.all(
                    uniqueTokens.map(async (token) =>
                        (await context.deps.quotaLimiting.isTeamTokenQuotaLimited(
                            token,
                            context.identity.quotaResource
                        ))
                            ? token
                            : null
                    )
                )
            ).filter((token): token is string => token !== null)
        )

        const droppedByTeam = new Map<number, number>()
        const results = values.map((value): PipelineResult<T> => {
            if (isUnbilledInternal(value) || !limited.has(value.token)) {
                return ok(value)
            }
            droppedByTeam.set(value.teamId, (droppedByTeam.get(value.teamId) ?? 0) + 1)
            value.usage.recordDropped(value)
            return drop('quota_limited')
        })
        countMessagesDropped('quota_limited', droppedByTeam)
        return results
    }
}

export function createRateLimitStep<T extends LogsAdmissionInput>(
    context: LogsPipelineContext
): ChunkProcessingStep<T, T> {
    return async function rateLimitStep(values) {
        const billed = values.filter((value) => !isUnbilledInternal(value))
        const { dropped } = await context.rateLimiter.filterMessages(billed)
        const droppedSet = new Set<LogsIngestionMessage>(dropped)

        const droppedByTeam = new Map<number, number>()
        const results = values.map((value): PipelineResult<T> => {
            if (!droppedSet.has(value)) {
                return ok(value)
            }
            droppedByTeam.set(value.teamId, (droppedByTeam.get(value.teamId) ?? 0) + 1)
            value.usage.recordDropped(value)
            return drop('rate_limited')
        })
        countMessagesDropped('rate_limited', droppedByTeam)
        return results
    }
}

/** Allowed is gross here, because processing takes off the drop-rule billing credit. */
export function createRecordAllowedUsageStep<T extends LogsAdmissionInput>(): ChunkProcessingStep<T, T> {
    return function recordAllowedUsageStep(values) {
        let bytesAllowed = 0
        let recordsAllowed = 0
        let bytesAllowedRecords = 0
        for (const value of values) {
            if (isUnbilledInternal(value)) {
                continue
            }
            value.usage.recordAllowed(value)
            bytesAllowed += value.bytesUncompressed
            bytesAllowedRecords += value.bytesUncompressedRecords
            recordsAllowed += value.recordCount
        }

        logsBytesAllowedRecordsCounter.inc(bytesAllowedRecords)
        logsBytesAllowedCounter.inc(bytesAllowed)
        logsRecordsAllowedCounter.inc(recordsAllowed)
        recordLogsAllowed(bytesAllowed, recordsAllowed)
        return Promise.resolve(values.map((value) => ok(value)))
    }
}

/** Runs after admission even when every message was dropped, which no chunk step does. */
export function reportDroppedUsage(usage: LogsBatchUsage): void {
    for (const [teamId, stats] of usage.byTeam) {
        const teamIdLabel = teamId.toString()
        if (stats.bytesDropped > 0) {
            logsBytesDroppedCounter.inc({ team_id: teamIdLabel }, stats.bytesDropped)
        }
        if (stats.recordsDropped > 0) {
            logsRecordsDroppedCounter.inc({ team_id: teamIdLabel }, stats.recordsDropped)
        }
        recordLogsDropped(teamId, stats.bytesDropped, stats.recordsDropped)
    }
}
