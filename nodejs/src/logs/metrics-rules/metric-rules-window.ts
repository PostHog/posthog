import { logger } from '~/common/utils/logger'

import type { CompiledMetricRule } from './compile-metric-rules'
import type { LogsMetricsEmitter } from './metrics-emitter'
import { buildMetricRulesOtlpPayload } from './otlp-payload'
import { type BatchTallies, type MetricTallyEntry, createBatchTallies } from './tally'

/** `otlp-payload.ts` stamps points on 10 s boundaries, so window starts must land on them. */
const WINDOW_STEP_MS = 10_000

export const DEFAULT_METRIC_RULES_WINDOW_MS = 60_000

export type MetricRuleTeamTallies = { token: string; rules: CompiledMetricRule[]; tallies: BatchTallies }

export type MetricRuleWindowFlush = MetricRuleTeamTallies & { teamId: number; windowStartMs: number }

export function normalizeMetricRulesWindowMs(windowMs: number): number {
    if (!Number.isFinite(windowMs) || windowMs <= 0) {
        return DEFAULT_METRIC_RULES_WINDOW_MS
    }
    return Math.max(1, Math.round(windowMs / WINDOW_STEP_MS)) * WINDOW_STEP_MS
}

/** A rule edited mid-window must not merge counter tallies into histogram ones, so each shape gets its own key. */
function ruleShapeKey(rule: CompiledMetricRule): string {
    return JSON.stringify([rule.id, rule.metricName, rule.valueAttribute, rule.groupBy])
}

function mergeEntry(target: MetricTallyEntry, source: MetricTallyEntry): void {
    target.count += source.count
    target.sum += source.sum
    if (target.bucketCounts && source.bucketCounts) {
        for (let i = 0; i < target.bucketCounts.length; i++) {
            target.bucketCounts[i]! += source.bucketCounts[i] ?? 0
        }
    }
    if (!target.exemplarTraceId && source.exemplarTraceId) {
        target.exemplarTraceId = source.exemplarTraceId
        target.exemplarSpanId = source.exemplarSpanId
    }
}

type PendingTeam = { token: string; rules: Map<string, CompiledMetricRule>; tallies: BatchTallies }

/**
 * Every consumer pod writes the same series, so a series gets pods × 3600 / window points an hour.
 * No timer: a window closes at the end of the next batch, keeping its start timestamp.
 */
export class MetricRulesWindowAggregator {
    private windowStartMs: number | null = null
    private pending = new Map<number, PendingTeam>()

    constructor(public readonly windowMs: number = DEFAULT_METRIC_RULES_WINDOW_MS) {
        this.windowMs = normalizeMetricRulesWindowMs(windowMs)
    }

    public get hasPending(): boolean {
        return this.pending.size > 0
    }

    public add(teamId: number, batch: MetricRuleTeamTallies, nowMs: number): void {
        if (this.windowStartMs === null) {
            this.windowStartMs = Math.floor(nowMs / this.windowMs) * this.windowMs
        }
        let team = this.pending.get(teamId)
        if (!team) {
            team = { token: batch.token, rules: new Map(), tallies: createBatchTallies() }
            this.pending.set(teamId, team)
        }
        team.token = batch.token
        team.tallies.valueSkipped += batch.tallies.valueSkipped
        team.tallies.evalErrors += batch.tallies.evalErrors

        for (const rule of batch.rules) {
            const ruleTallies = batch.tallies.byRule.get(rule.id)
            if (!ruleTallies?.size) {
                continue
            }
            const key = ruleShapeKey(rule)
            if (!team.rules.has(key)) {
                team.rules.set(key, { ...rule, id: key })
            }
            let target = team.tallies.byRule.get(key)
            if (!target) {
                target = new Map()
                team.tallies.byRule.set(key, target)
            }
            for (const [labelKey, entry] of ruleTallies) {
                const existing = target.get(labelKey)
                if (existing) {
                    mergeEntry(existing, entry)
                } else {
                    target.set(labelKey, {
                        ...entry,
                        labelValues: [...entry.labelValues],
                        bucketCounts: entry.bucketCounts ? [...entry.bucketCounts] : null,
                    })
                }
            }
            const overflow = batch.tallies.seriesOverflow.get(rule.id)
            if (overflow) {
                team.tallies.seriesOverflow.set(key, (team.tallies.seriesOverflow.get(key) ?? 0) + overflow)
            }
        }
    }

    public takeClosed(nowMs: number): MetricRuleWindowFlush[] {
        if (this.windowStartMs === null || nowMs < this.windowStartMs + this.windowMs) {
            return []
        }
        return this.takeAll()
    }

    public takeAll(): MetricRuleWindowFlush[] {
        const windowStartMs = this.windowStartMs
        const pending = this.pending
        this.windowStartMs = null
        this.pending = new Map()
        if (windowStartMs === null) {
            return []
        }
        return [...pending.entries()].map(([teamId, team]) => ({
            teamId,
            token: team.token,
            rules: [...team.rules.values()],
            tallies: team.tallies,
            windowStartMs,
        }))
    }
}

export class MetricRulesEmission {
    private readonly aggregator: MetricRulesWindowAggregator

    constructor(
        private readonly emitter: Pick<LogsMetricsEmitter, 'emit'> | undefined,
        private readonly isWindowedTeam: (teamId: number) => boolean,
        windowMs: number = DEFAULT_METRIC_RULES_WINDOW_MS
    ) {
        this.aggregator = new MetricRulesWindowAggregator(windowMs)
    }

    public async emitBatch(byTeam: Map<number, MetricRuleTeamTallies>, nowMs: number = Date.now()): Promise<void> {
        // Take the closed window before adding, so this batch's counts open the next window.
        const closed = this.aggregator.takeClosed(nowMs)
        for (const [teamId, batch] of byTeam) {
            if (this.isWindowedTeam(teamId)) {
                this.aggregator.add(teamId, batch, nowMs)
            } else {
                await this.send(teamId, batch.token, batch.rules, batch.tallies, nowMs)
            }
        }
        await this.sendFlushes(closed)
    }

    public async flushAll(): Promise<void> {
        await this.sendFlushes(this.aggregator.takeAll())
    }

    private async sendFlushes(flushes: MetricRuleWindowFlush[]): Promise<void> {
        for (const flush of flushes) {
            await this.send(flush.teamId, flush.token, flush.rules, flush.tallies, flush.windowStartMs)
        }
    }

    private async send(
        teamId: number,
        token: string,
        rules: CompiledMetricRule[],
        tallies: BatchTallies,
        timeMs: number
    ): Promise<void> {
        const payload = buildMetricRulesOtlpPayload(rules, tallies, timeMs)
        if (!payload || !this.emitter) {
            return
        }
        try {
            await this.emitter.emit(token, teamId, payload)
        } catch (error) {
            // Emission is best-effort: a failing metrics endpoint must never fail log ingestion.
            logger.warn('[logs-metric-rules] emit threw', { teamId, error: String(error) })
        }
    }
}
