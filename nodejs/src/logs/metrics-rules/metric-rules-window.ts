import { logger } from '~/common/utils/logger'

import type { CompiledMetricRule } from './compile-metric-rules'
import type { LogsMetricsEmitter } from './metrics-emitter'
import { buildMetricRulesOtlpPayload } from './otlp-payload'
import { type BatchTallies, type MetricTallyEntry, createBatchTallies } from './tally'

/** `otlp-payload.ts` stamps points on 10 s boundaries, so window starts must land on them. */
const WINDOW_STEP_MS = 10_000

export const DEFAULT_METRIC_RULES_WINDOW_MS = 60_000

/** Under capture-logs' default 2 MiB body limit, with room for headers and the token. */
export const MAX_METRIC_RULES_REQUEST_BYTES = 1_500_000

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
 * A window closes at the end of the next batch, or on the idle timer in `MetricRulesEmission`, keeping its start timestamp.
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

    /** When the open window expires, or null when nothing is pending. */
    public get closesAtMs(): number | null {
        return this.windowStartMs === null ? null : this.windowStartMs + this.windowMs
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

/**
 * Splits one team's tallies into parts whose OTLP payload stays under `maxBytes`, halving until each fits.
 * A single label set over the limit is sent alone and left for capture to reject.
 */
export function buildSizeBoundedPayloads(
    rules: CompiledMetricRule[],
    tallies: BatchTallies,
    timeMs: number,
    maxBytes: number = MAX_METRIC_RULES_REQUEST_BYTES
): Record<string, unknown>[] {
    const payload = buildMetricRulesOtlpPayload(rules, tallies, timeMs)
    if (!payload) {
        return []
    }
    if (Buffer.byteLength(JSON.stringify(payload)) <= maxBytes) {
        return [payload]
    }
    const entries: [string, string, MetricTallyEntry][] = []
    for (const [ruleId, ruleTallies] of tallies.byRule) {
        for (const [labelKey, entry] of ruleTallies) {
            entries.push([ruleId, labelKey, entry])
        }
    }
    if (entries.length <= 1) {
        return [payload]
    }
    const half = Math.ceil(entries.length / 2)
    return [entries.slice(0, half), entries.slice(half)].flatMap((part) => {
        const partTallies = createBatchTallies()
        for (const [ruleId, labelKey, entry] of part) {
            let ruleTallies = partTallies.byRule.get(ruleId)
            if (!ruleTallies) {
                ruleTallies = new Map()
                partTallies.byRule.set(ruleId, ruleTallies)
            }
            ruleTallies.set(labelKey, entry)
        }
        return buildSizeBoundedPayloads(rules, partTallies, timeMs, maxBytes)
    })
}

export class MetricRulesEmission {
    private readonly aggregator: MetricRulesWindowAggregator
    private idleTimer: NodeJS.Timeout | null = null
    private idleFlush: Promise<void> | null = null
    private stopping = false

    constructor(
        private readonly emitter: Pick<LogsMetricsEmitter, 'emit'> | undefined,
        private readonly isWindowedTeam: (teamId: number) => boolean,
        windowMs: number = DEFAULT_METRIC_RULES_WINDOW_MS
    ) {
        this.aggregator = new MetricRulesWindowAggregator(windowMs)
    }

    public async emitBatch(byTeam: Map<number, MetricRuleTeamTallies>, nowMs: number = Date.now()): Promise<void> {
        const startedAtMs = Date.now()
        // Take the closed window before adding, so this batch's counts open the next window.
        // No await until every add is done, so batches running concurrently never see half a batch in a window.
        const closed = this.aggregator.takeClosed(nowMs)
        const perBatch: [number, MetricRuleTeamTallies][] = []
        for (const [teamId, batch] of byTeam) {
            if (this.isWindowedTeam(teamId)) {
                this.aggregator.add(teamId, batch, nowMs)
            } else {
                perBatch.push([teamId, batch])
            }
        }
        for (const [teamId, batch] of perBatch) {
            await this.send(teamId, batch.token, batch.rules, batch.tallies, nowMs)
        }
        // Exports for teams outside the window took time, and the timer must still fire when the window ends.
        this.scheduleIdleFlush(nowMs + (Date.now() - startedAtMs))
        await this.sendFlushes(closed)
    }

    /** Sends the open window once it expires, for when no batch arrives to close it. */
    public async flushExpired(nowMs: number = Date.now()): Promise<void> {
        const closed = this.aggregator.takeClosed(nowMs)
        this.scheduleIdleFlush(nowMs)
        await this.sendFlushes(closed)
    }

    /** Sends the open window on shutdown, and stops the idle timer for good. */
    public async flushAll(): Promise<void> {
        this.stopping = true
        await this.flushOpen()
    }

    /** Sends the open window now, as when partitions are revoked. Later batches open a new window as usual. */
    public async flushOpen(): Promise<void> {
        this.clearIdleTimer()
        // The timer may already hold the expired window; shutdown must not close the HTTP agents under its sends.
        await this.idleFlush
        await this.sendFlushes(this.aggregator.takeAll())
    }

    private scheduleIdleFlush(nowMs: number): void {
        this.clearIdleTimer()
        const closesAtMs = this.aggregator.closesAtMs
        if (closesAtMs === null || this.stopping) {
            return
        }
        this.idleTimer = setTimeout(
            () => {
                this.idleTimer = null
                // One timer flush at a time, so a slow endpoint cannot pile up windows in memory.
                // Batch-path flushes are awaited by the consumer, so at most two windows are ever sending.
                if (this.idleFlush) {
                    return
                }
                this.idleFlush = this.flushExpired().finally(() => {
                    this.idleFlush = null
                    // A window that expired while this flush was sending had its timer skipped.
                    this.scheduleIdleFlush(Date.now())
                })
            },
            Math.max(0, closesAtMs - nowMs)
        )
        // A pending window must not keep the process alive; shutdown sends it through `flushAll`.
        this.idleTimer.unref()
    }

    private clearIdleTimer(): void {
        if (this.idleTimer) {
            clearTimeout(this.idleTimer)
            this.idleTimer = null
        }
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
        if (!this.emitter) {
            return
        }
        for (const payload of buildSizeBoundedPayloads(rules, tallies, timeMs)) {
            try {
                await this.emitter.emit(token, teamId, payload)
            } catch (error) {
                // Emission is best-effort: a failing metrics endpoint must never fail log ingestion.
                logger.warn('[logs-metric-rules] emit threw', { teamId, error: String(error) })
            }
        }
    }
}
