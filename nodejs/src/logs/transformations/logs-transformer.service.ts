import { DateTime } from 'luxon'
import { Counter, Histogram } from 'prom-client'

import { HogFunctionManagerService } from '~/cdp/services/managers/hog-function-manager.service'
import { HogFunctionMonitoringService } from '~/cdp/services/monitoring/hog-function-monitoring.service'
import { HogWatcherService, HogWatcherState } from '~/cdp/services/monitoring/hog-watcher.service'
import { HogFunctionType, LogEntry } from '~/cdp/types'
import { yieldEventLoopIfNeeded } from '~/common/utils/event-loop-yield'
import { logger } from '~/common/utils/logger'
import { UUIDT } from '~/common/utils/utils'

import type { LogRecord } from '../log-record-avro'
import {
    LogTransformationGlobals,
    buildLogRecordGlobals,
    decodeLogAttributeValue,
    encodeLogAttributeValue,
    executeLogTransformation,
    resolveLogTransformationInputs,
} from './hog-log-exec'

export const transformationRecordsCounter = new Counter({
    name: 'logs_ingestion_transformations_records_total',
    help: 'Per-record log transformation outcomes',
    labelNames: ['result'], // succeeded | failed | dropped | budget_skipped | watcher_disabled
})

export const transformationVmDurationHistogram = new Histogram({
    name: 'logs_ingestion_transformations_vm_duration_seconds',
    help: 'Total HogVM execution time spent on log transformations per Kafka message',
    buckets: [0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2],
})

export const transformationBudgetExhaustedCounter = new Counter({
    name: 'logs_ingestion_transformations_budget_exhausted_total',
    help: 'Transformation time budget exhausted; remaining records passed through untransformed',
    labelNames: ['scope', 'team_id'], // scope: message | batch
})

export const transformationUnexpectedErrorsCounter = new Counter({
    name: 'logs_ingestion_transformations_unexpected_errors_total',
    help: 'Unexpected (non-customer-code) errors in the logs transformer. Any occurrence should alert.',
})

export interface LogsTransformerConfig {
    siteUrl: string
    /** Hard per-record VM kill */
    hogTimeoutMs: number
    /** Cumulative VM time budget per Kafka message */
    messageBudgetMs: number
    /** Cumulative VM time budget per consumer batch */
    batchBudgetMs: number
    /** Max failed invocations whose print/error logs are captured, per function per message */
    maxErrorLogsPerFunctionPerMessage: number
    /** Fraction of messages on which HogWatcher state is read and aggregate cost reported.
     * 0 disables the watcher entirely (no Redis reads, no observations). */
    hogWatcherSampleRate: number
}

/** Tracks cumulative VM time across all messages of one consumer batch. */
export class TransformationBatchBudget {
    usedMs = 0

    constructor(private readonly totalMs: number) {}

    get exhausted(): boolean {
        return this.usedMs >= this.totalMs
    }

    add(durationMs: number): void {
        this.usedMs += durationMs
    }
}

interface FunctionAggregates {
    succeeded: number
    failed: number
    dropped: number
    budgetSkipped: number
    totalDurationMs: number
    errorLogs: LogEntry[]
}

const ATTR_TRANSFORMATIONS_FAILED = '$transformations_failed'
const ATTR_TRANSFORMATIONS_SKIPPED = '$transformations_skipped'

/**
 * Runs a team's enabled log transformations over the records of one Kafka message,
 * mutating the array in place (dropped records are removed).
 *
 * Failure semantics are fail-open throughout, mirroring events ingestion and the
 * logs sampling pipeline: a failing transformation annotates the record and passes
 * it through unchanged. Budgets bound the worst-case added latency; when exhausted,
 * remaining records skip transformation and are annotated.
 *
 * Unlike the events HogTransformerService there are no per-invocation result objects:
 * at logs volume (100k+ records/s for large teams) metrics are aggregated per
 * (function, message) and print() output is only kept for failing invocations.
 */
export class LogsTransformerService {
    constructor(
        private hogFunctionManager: HogFunctionManagerService,
        private monitoring: HogFunctionMonitoringService,
        private config: LogsTransformerConfig,
        private hogWatcher?: HogWatcherService
    ) {}

    public startBatch(): TransformationBatchBudget {
        return new TransformationBatchBudget(this.config.batchBudgetMs)
    }

    /** Cheap existence check (in-process LazyLoader cache) used to preserve the
     * no-decode passthrough for teams without transformations. */
    public async teamHasTransformations(teamId: number): Promise<boolean> {
        const idsByTeam = await this.hogFunctionManager.getHogFunctionIdsForTeams([teamId], ['transformation_log'])
        return (idsByTeam[teamId] ?? []).length > 0
    }

    public async flush(): Promise<void> {
        await this.monitoring.flush()
    }

    public async transformRecords(
        teamId: number,
        records: LogRecord[],
        batchBudget?: TransformationBatchBudget
    ): Promise<{ recordsDropped: number; recordsDroppedByFunctionId: Map<string, number> }> {
        const recordsDroppedByFunctionId = new Map<string, number>()
        let recordsDropped = 0

        const functionsByTeam = await this.hogFunctionManager.getHogFunctionsForTeams([teamId], ['transformation_log'])
        const allFunctions = functionsByTeam[teamId] ?? []
        if (allFunctions.length === 0 || records.length === 0) {
            return { recordsDropped, recordsDroppedByFunctionId }
        }

        // On a sampled message the watcher reads state (to skip disabled functions) and, at the
        // end, receives the aggregate cost. A sample rate of 0 means no Redis traffic at all.
        const runWatcher = !!this.hogWatcher && Math.random() < this.config.hogWatcherSampleRate
        const functions = runWatcher
            ? await this.dropWatcherDisabled(teamId, allFunctions, records.length)
            : allFunctions
        if (functions.length === 0) {
            return { recordsDropped, recordsDroppedByFunctionId }
        }

        const project = {
            id: teamId,
            name: '',
            url: `${this.config.siteUrl}/project/${teamId}`,
        }
        const instanceId = new UUIDT().toString()
        const aggregates = new Map<string, FunctionAggregates>()
        const inputsCache = new Map<string, Record<string, unknown> | null>()
        const sensitiveValuesCache = new Map<string, string[]>()
        let messageVmMs = 0
        let budgetExhaustedScope: 'message' | 'batch' | null = null

        const kept: LogRecord[] = []

        for (let i = 0; i < records.length; i++) {
            const record = records[i]

            if (budgetExhaustedScope === null) {
                if (batchBudget?.exhausted) {
                    budgetExhaustedScope = 'batch'
                } else if (messageVmMs >= this.config.messageBudgetMs) {
                    budgetExhaustedScope = 'message'
                }
                if (budgetExhaustedScope !== null) {
                    transformationBudgetExhaustedCounter.inc({
                        scope: budgetExhaustedScope,
                        team_id: String(teamId),
                    })
                }
            }

            if (budgetExhaustedScope !== null) {
                record.attributes = record.attributes ?? {}
                // JSON-encoded like every attribute value, so the ClickHouse sink surfaces it
                record.attributes[ATTR_TRANSFORMATIONS_SKIPPED] = encodeLogAttributeValue('budget')
                transformationRecordsCounter.inc({ result: 'budget_skipped' })
                for (const fn of functions) {
                    this.getAggregates(aggregates, fn.id).budgetSkipped++
                }
                kept.push(record)
                continue
            }

            const dropped = await yieldEventLoopIfNeeded('logs-transformer', () => {
                return this.transformSingleRecord(record, functions, project, {
                    teamId,
                    instanceId,
                    aggregates,
                    inputsCache,
                    sensitiveValuesCache,
                    recordsDroppedByFunctionId,
                    addVmMs: (ms) => {
                        messageVmMs += ms
                        batchBudget?.add(ms)
                    },
                })
            })

            if (dropped) {
                recordsDropped++
            } else {
                kept.push(record)
            }
        }

        // Replace contents in place so callers holding the array reference see the result
        records.length = 0
        records.push(...kept)

        transformationVmDurationHistogram.observe(messageVmMs / 1000)
        this.queueAggregates(teamId, aggregates)
        if (runWatcher) {
            this.reportToWatcher(functions, aggregates)
        }

        return { recordsDropped, recordsDroppedByFunctionId }
    }

    /** Reads watcher state once per message and removes functions it has disabled. */
    private async dropWatcherDisabled(
        teamId: number,
        functions: HogFunctionType[],
        recordCount: number
    ): Promise<HogFunctionType[]> {
        if (!this.hogWatcher) {
            return functions
        }
        const states = await this.hogWatcher.getEffectiveStates(functions.map((fn) => fn.id))
        const active: HogFunctionType[] = []
        for (const fn of functions) {
            if (states[fn.id]?.state === HogWatcherState.disabled) {
                transformationRecordsCounter.inc({ result: 'watcher_disabled' }, recordCount)
                this.monitoring.queueAppMetric(
                    {
                        team_id: teamId,
                        app_source_id: fn.id,
                        metric_kind: 'failure',
                        metric_name: 'disabled_permanently',
                        count: recordCount,
                    },
                    'hog_function'
                )
            } else {
                active.push(fn)
            }
        }
        return active
    }

    /** Reports one aggregated VM-time observation per function for this message. Fire-and-forget. */
    private reportToWatcher(functions: HogFunctionType[], aggregates: Map<string, FunctionAggregates>): void {
        if (!this.hogWatcher) {
            return
        }
        const byId = new Map(functions.map((fn) => [fn.id, fn]))
        const observations: { hogFunction: HogFunctionType; totalDurationMs: number }[] = []
        for (const [functionId, agg] of aggregates) {
            const hogFunction = byId.get(functionId)
            // A 0ms aggregate still costs nothing, but reporting it keeps token refill honest.
            if (hogFunction) {
                observations.push({ hogFunction, totalDurationMs: agg.totalDurationMs })
            }
        }
        if (observations.length > 0) {
            this.hogWatcher.observeAggregatedResults(observations).catch((error) => {
                logger.warn('⚠️', '[logs-transformer] HogWatcher observeAggregatedResults failed', {
                    error: String(error),
                })
            })
        }
    }

    /** Runs every function in execution order against one record. Returns true if dropped. */
    private transformSingleRecord(
        record: LogRecord,
        functions: HogFunctionType[],
        project: LogTransformationGlobals['project'],
        ctx: {
            teamId: number
            instanceId: string
            aggregates: Map<string, FunctionAggregates>
            inputsCache: Map<string, Record<string, unknown> | null>
            sensitiveValuesCache: Map<string, string[]>
            recordsDroppedByFunctionId: Map<string, number>
            addVmMs: (ms: number) => void
        }
    ): boolean {
        for (const fn of functions) {
            const agg = this.getAggregates(ctx.aggregates, fn.id)

            const globals = buildLogRecordGlobals(record, project, {})

            // Input templates are customer-owned bytecode — a failing template is an
            // invocation failure (fail open, annotate, surface in function logs), not a
            // transformer bug worth alerting on.
            try {
                const { inputs, vmMs } = this.resolveInputs(fn, globals, ctx.inputsCache)
                globals.inputs = inputs
                ctx.addVmMs(vmMs)
                agg.totalDurationMs += vmMs
            } catch (error) {
                agg.failed++
                transformationRecordsCounter.inc({ result: 'failed' })
                this.annotateFailure(record, fn)
                this.captureErrorLogs(fn, ctx.teamId, ctx.instanceId, agg, [], String(error))
                continue
            }

            let outcome
            try {
                outcome = executeLogTransformation(fn.bytecode, record, globals, {
                    timeoutMs: this.config.hogTimeoutMs,
                    sensitiveValues: this.getSensitiveValues(fn, ctx.sensitiveValuesCache),
                })
            } catch (error) {
                // Errors from customer code are contained inside executeLogTransformation;
                // reaching here means a transformer bug.
                transformationUnexpectedErrorsCounter.inc()
                logger.error('⚠️', '[logs-transformer] unexpected error', {
                    teamId: ctx.teamId,
                    functionId: fn.id,
                    error: String(error),
                })
                this.annotateFailure(record, fn)
                agg.failed++
                transformationRecordsCounter.inc({ result: 'failed' })
                continue
            }

            ctx.addVmMs(outcome.durationMs)
            agg.totalDurationMs += outcome.durationMs

            if (outcome.status === 'failed') {
                agg.failed++
                transformationRecordsCounter.inc({ result: 'failed' })
                this.annotateFailure(record, fn)
                this.captureErrorLogs(fn, ctx.teamId, ctx.instanceId, agg, outcome.logs, outcome.error)
                continue
            }

            if (outcome.status === 'dropped') {
                agg.dropped++
                transformationRecordsCounter.inc({ result: 'dropped' })
                ctx.recordsDroppedByFunctionId.set(fn.id, (ctx.recordsDroppedByFunctionId.get(fn.id) ?? 0) + 1)
                return true
            }

            agg.succeeded++
            transformationRecordsCounter.inc({ result: 'succeeded' })
        }

        return false
    }

    /**
     * Resolves function inputs once per (function, message) and caches them — unless any
     * input template references the `record` global, in which case resolution happens per
     * record (cache stores null to remember that decision).
     */
    private resolveInputs(
        fn: HogFunctionType,
        globals: LogTransformationGlobals,
        cache: Map<string, Record<string, unknown> | null>
    ): { inputs: Record<string, unknown>; vmMs: number } {
        const cached = cache.get(fn.id)
        if (cached) {
            return { inputs: cached, vmMs: 0 }
        }

        if (cached === undefined) {
            // First sight of this function in this message: decide cacheability with a
            // cheap scan over all templates (encrypted included). False positives only
            // cost per-record resolution.
            const referencesRecord = JSON.stringify({ ...fn.inputs, ...fn.encrypted_inputs }).includes('record')
            if (!referencesRecord) {
                const resolved = this.resolveInputsUncached(fn, globals)
                cache.set(fn.id, resolved.inputs)
                return { inputs: resolved.inputs, vmMs: resolved.durationMs }
            }
            cache.set(fn.id, null)
        }

        const resolved = this.resolveInputsUncached(fn, globals)
        return { inputs: resolved.inputs, vmMs: resolved.durationMs }
    }

    private resolveInputsUncached(
        fn: HogFunctionType,
        globals: LogTransformationGlobals
    ): { inputs: Record<string, unknown>; durationMs: number } {
        return resolveLogTransformationInputs(fn, globals, this.config.hogTimeoutMs)
    }

    private getSensitiveValues(fn: HogFunctionType, cache: Map<string, string[]>): string[] {
        let values = cache.get(fn.id)
        if (!values) {
            values = Object.values(fn.encrypted_inputs ?? {})
                .map((input) => input?.value)
                .filter((value): value is string => typeof value === 'string' && value.length > 0)
            cache.set(fn.id, values)
        }
        return values
    }

    private annotateFailure(record: LogRecord, fn: HogFunctionType): void {
        record.attributes = record.attributes ?? {}
        const rawExisting = record.attributes[ATTR_TRANSFORMATIONS_FAILED]
        const existing = rawExisting ? decodeLogAttributeValue(rawExisting) : undefined
        const identifier = `${fn.name} (${fn.id})`
        record.attributes[ATTR_TRANSFORMATIONS_FAILED] = encodeLogAttributeValue(
            existing ? `${existing}, ${identifier}` : identifier
        )
    }

    private captureErrorLogs(
        fn: HogFunctionType,
        teamId: number,
        instanceId: string,
        agg: FunctionAggregates,
        printLogs: string[],
        error: string
    ): void {
        const capturedFailures = agg.errorLogs.filter((log) => log.level === 'error').length
        if (capturedFailures >= this.config.maxErrorLogsPerFunctionPerMessage) {
            return
        }

        const base = {
            team_id: teamId,
            log_source: 'hog_function' as const,
            log_source_id: fn.id,
            instance_id: instanceId,
        }
        for (const message of printLogs) {
            agg.errorLogs.push({ ...base, level: 'info', message, timestamp: DateTime.now() })
        }
        agg.errorLogs.push({ ...base, level: 'error', message: error, timestamp: DateTime.now() })
    }

    private getAggregates(aggregates: Map<string, FunctionAggregates>, functionId: string): FunctionAggregates {
        let agg = aggregates.get(functionId)
        if (!agg) {
            agg = { succeeded: 0, failed: 0, dropped: 0, budgetSkipped: 0, totalDurationMs: 0, errorLogs: [] }
            aggregates.set(functionId, agg)
        }
        return agg
    }

    private queueAggregates(teamId: number, aggregates: Map<string, FunctionAggregates>): void {
        for (const [functionId, agg] of aggregates) {
            if (agg.succeeded > 0) {
                this.monitoring.queueAppMetric(
                    {
                        team_id: teamId,
                        app_source_id: functionId,
                        metric_kind: 'success',
                        metric_name: 'succeeded',
                        count: agg.succeeded,
                    },
                    'hog_function'
                )
            }
            if (agg.failed > 0) {
                this.monitoring.queueAppMetric(
                    {
                        team_id: teamId,
                        app_source_id: functionId,
                        metric_kind: 'failure',
                        metric_name: 'failed',
                        count: agg.failed,
                    },
                    'hog_function'
                )
            }
            if (agg.dropped > 0) {
                this.monitoring.queueAppMetric(
                    {
                        team_id: teamId,
                        app_source_id: functionId,
                        metric_kind: 'other',
                        metric_name: 'dropped',
                        count: agg.dropped,
                    },
                    'hog_function'
                )
            }
            if (agg.budgetSkipped > 0) {
                this.monitoring.queueAppMetric(
                    {
                        team_id: teamId,
                        app_source_id: functionId,
                        metric_kind: 'other',
                        metric_name: 'budget_skipped',
                        count: agg.budgetSkipped,
                    },
                    'hog_function'
                )
            }
            if (agg.errorLogs.length > 0) {
                this.monitoring.queueLogs(agg.errorLogs, 'hog_function')
            }
        }
    }
}
