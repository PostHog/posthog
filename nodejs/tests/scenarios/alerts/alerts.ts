import { readFileSync } from 'fs'
import { setTimeout as sleep } from 'timers/promises'
import { parse, stringify } from 'yaml'
import { z } from 'zod'

import type { AlertsProfile } from '../cards/schema'
import type { ValveTimelineEntry } from '../valves/valves'
import { Engine, ScrapeTarget, startEngine } from './engine'
import { readsOf } from './selectors'

const POLL_MS = 5000
const SCRAPE_INTERVAL_MS = 5000
const NEVER_EVALUATED = 'vmalert did not evaluate it during the run'
const COMPARISON = /(>=|<=|==|!=|>|<)\s*(?:bool\s+)?(-?[0-9.]+(?:e[+-]?[0-9]+)?)/gi
const POLLS_PER_INTERVAL = 4
const MISSED_AFTER_INTERVALS = 1.5
const MISSED_EVALUATIONS = 'missed evaluations'
const QUOTED = /"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|`[^`]*`/g

export type AlertState = 'pending' | 'firing' | 'resolved'

export type AlertTransition = {
    at: number
    latest?: number
    rule: string
    instance: string
    tier?: string
    labels: Record<string, string>
    state: AlertState
    value: number | null
    threshold?: { op: string; value: number }
    for: number
    runbook?: string
}

type RuleLine =
    | { type: 'rule'; rule: string; state: 'evaluated' }
    | { type: 'rule'; rule: string; state: 'unevaluable'; selectors: string[]; error?: string }
    | { type: 'rule'; rule: string; state: 'excluded' }

export type AlertGap = { from: number; to: number; reason: string; rules?: string[] }

type Since = { sinceDriveMs: number; sinceValves: { valve: string; target: string; sinceMs: number }[] }

export type AlertLine = ({ type: 'transition' } & AlertTransition & Since) | ({ type: 'gap' } & AlertGap) | RuleLine

export type AlertCoverage =
    | {
          evaluated: string[]
          fired: string[]
          unevaluable: { rule: string; selectors: string[]; error?: string }[]
          excluded: string[]
          gaps: AlertGap[]
      }
    | { unread: string }

export type AlertsRead = { lines: AlertLine[]; coverage: AlertCoverage }

export type AlertsOptions = {
    alerts: AlertsProfile
    targets: ScrapeTarget[]
    onTransition(transition: AlertTransition): void
    scrapeIntervalMs?: number
    pollMs?: number
}

export interface Alerts {
    finish(drive: { startedAt: number }, timeline: readonly ValveTimelineEntry[], judgedAt: number): Promise<AlertsRead>
    close(): Promise<void>
}

const Labels = z.record(z.string(), z.string())
const VmAlert = z.object({
    id: z.string(),
    state: z.enum(['pending', 'firing']),
    activeAt: z.string(),
    value: z.string(),
    labels: Labels,
    annotations: Labels.optional(),
})
const VmRule = z.object({
    id: z.string(),
    name: z.string(),
    query: z.string(),
    duration: z.number(),
    lastError: z.string(),
    lastEvaluation: z.string(),
    alerts: z.array(VmAlert).nullish(),
})
const VmRules = z.object({
    data: z.object({ groups: z.array(z.object({ interval: z.number(), rules: z.array(VmRule) })) }),
})
const Expanded = z.object({ expr: z.string() })
const Series = z.object({ data: z.array(z.unknown()) })
type VmAlert = z.infer<typeof VmAlert>
type VmRule = z.infer<typeof VmRule>

const messageOf = (error: unknown): string => (error instanceof Error ? error.message : String(error))

function withoutExcluded(file: string, exclude: string[]): { rules: string; excluded: string[] } {
    const { groups } = parse(readFileSync(file, 'utf8')) as { groups: { rules: { alert?: string }[] }[] }
    const names = groups.flatMap(({ rules }) => rules.flatMap(({ alert }) => (alert === undefined ? [] : [alert])))
    const repeated = names.find((name, index) => names.indexOf(name) !== index)
    if (repeated !== undefined) {
        throw new Error(`the rules file names the alert ${repeated} more than once`)
    }
    const left = (alert?: string): boolean => alert !== undefined && exclude.includes(alert)
    return {
        rules: stringify({
            groups: groups.map((group) => ({ ...group, rules: group.rules.filter(({ alert }) => !left(alert)) })),
        }),
        excluded: groups.flatMap(({ rules }) => rules.flatMap(({ alert }) => (left(alert) ? [alert!] : []))),
    }
}

function thresholdOf(query: string): AlertTransition['threshold'] {
    const unquoted = query.replace(QUOTED, '""')
    const comparisons = [...unquoted.matchAll(COMPARISON)]
    const [only] = comparisons
    return comparisons.length === 1 && unquoted.slice(only.index + only[0].length).trim() === ''
        ? { op: only[1], value: Number(only[2]) }
        : undefined
}

function evaluationAfter(activeAt: number, evaluatedAt: number, intervalMs: number): number {
    return activeAt + (Math.floor((evaluatedAt - activeAt) / intervalMs) + 1) * intervalMs
}

function transitionOf(rule: VmRule, alert: VmAlert, state: AlertState, at: number, latest?: number): AlertTransition {
    const value = Number(alert.value)
    const threshold = thresholdOf(rule.query)
    return {
        at,
        ...(latest !== undefined && latest > at && { latest }),
        rule: rule.name,
        instance: alert.id,
        ...(alert.labels.severity !== undefined && { tier: alert.labels.severity }),
        labels: alert.labels,
        state,
        value: state !== 'resolved' && Number.isFinite(value) ? value : null,
        ...(threshold && { threshold }),
        for: rule.duration,
        ...(alert.annotations?.runbook_url !== undefined && { runbook: alert.annotations.runbook_url }),
    }
}

async function missingSelectorsOf(engine: Engine, query: string, since: number): Promise<string[]> {
    const { expr } = Expanded.parse(await engine.metrics('/expand-with-exprs', { query, format: 'json' }))
    const missing = []
    for (const { selector, offsetSeconds } of readsOf(expr)) {
        // An offset reads samples from before now, and the metrics store holds none from before the run.
        const end = Math.ceil(Date.now() / 1000 - offsetSeconds)
        const found =
            end > since &&
            Series.parse(
                await engine.metrics('/api/v1/series', {
                    'match[]': selector,
                    start: `${since}`,
                    end: `${end}`,
                    limit: '1',
                })
            ).data.length > 0
        if (!found) {
            missing.push(offsetSeconds === 0 ? selector : `${selector} offset ${offsetSeconds}s`)
        }
    }
    return missing
}

function coverageOf(lines: RuleLine[], fired: string[], gaps: AlertGap[]): AlertCoverage {
    const named = (state: RuleLine['state']): string[] =>
        lines.flatMap((line) => (line.state === state ? [line.rule] : []))
    return {
        evaluated: named('evaluated'),
        fired,
        unevaluable: lines.flatMap((line) =>
            line.state === 'unevaluable'
                ? [{ rule: line.rule, selectors: line.selectors, ...(line.error && { error: line.error }) }]
                : []
        ),
        excluded: named('excluded'),
        gaps,
    }
}

function sinceOf(at: number, drive: { startedAt: number }, timeline: readonly ValveTimelineEntry[]): Since {
    return {
        sinceDriveMs: at - drive.startedAt,
        sinceValves: timeline.flatMap(({ valve, target, appliedAt }) =>
            appliedAt === undefined ? [] : [{ valve, target, sinceMs: at - Date.parse(appliedAt) }]
        ),
    }
}

export function recordAlerts(engine: Engine, since: number, excluded: string[], options: AlertsOptions): Alerts {
    const transitions: AlertTransition[] = []
    const errors = new Map<string, string>()
    const open = new Map<string, { rule: VmRule; alert: VmAlert }>()
    const evaluatedAt = new Map<string, number>()
    const missed = new Map<string, AlertGap & { rules: string[] }>()
    const failedReads: AlertGap[] = []
    let failing: { from: number; reason: string } | undefined
    let readAt = since * 1000
    let rules: VmRule[] = []
    const record = (transition: AlertTransition): void => {
        transitions.push(transition)
        options.onTransition(transition)
    }
    let pollMs = options.pollMs ?? POLL_MS
    const read = async (): Promise<void> => {
        const { data } = VmRules.parse(await engine.alerting('/api/v1/rules', { type: 'alert' }))
        rules = data.groups.flatMap((group) => group.rules)
        const intervalMsOf = new Map(
            data.groups.flatMap(({ interval, rules }) =>
                rules.map(({ id }): [string, number] => [id, Math.round(interval * 1000)])
            )
        )
        const shortestMs = Math.min(...data.groups.map(({ interval }) => interval * 1000))
        pollMs = options.pollMs ?? Math.min(POLL_MS, shortestMs / POLLS_PER_INTERVAL)
        const recovering = failing !== undefined
        const jumped = new Map<string, number>()
        for (const rule of rules) {
            const evaluated = Date.parse(rule.lastEvaluation)
            // vmalert reports the year 1 for a rule it has not evaluated yet.
            if (!(evaluated > 0)) {
                continue
            }
            const before = evaluatedAt.get(rule.id)
            evaluatedAt.set(rule.id, evaluated)
            if (before === undefined || evaluated - before <= MISSED_AFTER_INTERVALS * intervalMsOf.get(rule.id)!) {
                continue
            }
            jumped.set(rule.id, evaluated)
            // The failed read already reports this window, with its error.
            if (!recovering) {
                const key = JSON.stringify([before, evaluated])
                const gap = missed.get(key) ?? { from: before, to: evaluated, reason: MISSED_EVALUATIONS, rules: [] }
                gap.rules.push(rule.name)
                missed.set(key, gap)
            }
        }
        const seen = new Set<string>()
        for (const rule of rules) {
            if (rule.lastError) {
                errors.set(rule.name, rule.lastError)
            } else {
                errors.delete(rule.name)
            }
            const intervalMs = intervalMsOf.get(rule.id)!
            for (const alert of rule.alerts ?? []) {
                const key = JSON.stringify([rule.id, alert.id])
                const activeAt = Date.parse(alert.activeAt)
                let previous = open.get(key)
                if (previous !== undefined && Date.parse(previous.alert.activeAt) !== activeAt) {
                    const ended = evaluationAfter(
                        Date.parse(previous.alert.activeAt),
                        Date.parse(previous.rule.lastEvaluation),
                        intervalMs
                    )
                    record(transitionOf(previous.rule, previous.alert, 'resolved', ended, activeAt))
                    previous = undefined
                }
                const was = previous?.alert.state
                seen.add(key)
                if (was === undefined && (alert.state === 'pending' || rule.duration > 0)) {
                    const pending = transitionOf(rule, alert, 'pending', activeAt)
                    record(alert.state === 'pending' ? pending : { ...pending, value: null })
                }
                if (alert.state === 'firing' && was !== 'firing') {
                    const due = activeAt + Math.ceil(Math.round(rule.duration * 1000) / intervalMs) * intervalMs
                    const afterPending =
                        was === 'pending'
                            ? evaluationAfter(activeAt, Date.parse(previous!.rule.lastEvaluation), intervalMs)
                            : due
                    record(transitionOf(rule, alert, 'firing', Math.max(due, afterPending), jumped.get(rule.id)))
                }
                open.set(key, { rule, alert })
            }
        }
        for (const [key, { rule, alert }] of open) {
            if (!seen.has(key)) {
                open.delete(key)
                const at = evaluationAfter(
                    Date.parse(alert.activeAt),
                    Date.parse(rule.lastEvaluation),
                    intervalMsOf.get(rule.id)!
                )
                record(transitionOf(rule, alert, 'resolved', at, jumped.get(rule.id)))
            }
        }
    }
    const recovered = (): void => {
        readAt = Date.now()
        if (failing !== undefined) {
            failedReads.push({ ...failing, to: readAt })
            failing = undefined
        }
    }
    const gapsOf = (): AlertGap[] => [...failedReads, ...missed.values()].sort((a, b) => a.from - b.from)
    const stopped = new AbortController()
    const polling = (async () => {
        while (!stopped.signal.aborted) {
            await read().then(recovered, (error: unknown) => {
                failing ??= { from: readAt, reason: messageOf(error) }
            })
            await sleep(pollMs, undefined, { signal: stopped.signal }).catch(() => undefined)
        }
    })()
    const transitionLines = (drive: { startedAt: number }, timeline: readonly ValveTimelineEntry[]): AlertLine[] =>
        transitions.map((transition) => ({
            type: 'transition' as const,
            ...transition,
            ...sinceOf(transition.at, drive, timeline),
        }))
    const gapLines = (): AlertLine[] => gapsOf().map((gap) => ({ type: 'gap' as const, ...gap }))
    let closed: Promise<void> | undefined
    const close = (): Promise<void> =>
        (closed ??= (async () => {
            stopped.abort()
            await polling
            await engine.stop()
        })())
    const finish = async (
        drive: { startedAt: number },
        timeline: readonly ValveTimelineEntry[],
        judgedAt: number
    ): Promise<AlertsRead> => {
        stopped.abort()
        await polling
        await read()
        recovered()
        const fired = transitions.filter(
            ({ state, at, latest }) => state === 'firing' && at >= drive.startedAt && (latest ?? at) <= judgedAt
        )
        const ruleLines: RuleLine[] = []
        for (const { name: rule, query, lastEvaluation } of rules) {
            const selectors = await missingSelectorsOf(engine, query, since)
            const error = errors.get(rule) ?? (Date.parse(lastEvaluation) >= since * 1000 ? undefined : NEVER_EVALUATED)
            ruleLines.push(
                selectors.length > 0 || error !== undefined
                    ? { type: 'rule', rule, state: 'unevaluable', selectors, ...(error && { error }) }
                    : { type: 'rule', rule, state: 'evaluated' }
            )
        }
        ruleLines.push(...excluded.map((rule): RuleLine => ({ type: 'rule', rule, state: 'excluded' })))
        return {
            lines: [...transitionLines(drive, timeline), ...gapLines(), ...ruleLines],
            coverage: coverageOf(ruleLines, [...new Set(fired.map(({ rule }) => rule))], gapsOf()),
        }
    }
    return {
        finish: (drive, timeline, judgedAt) =>
            finish(drive, timeline, judgedAt)
                .catch((error: unknown) => ({
                    lines: [...transitionLines(drive, timeline), ...gapLines()],
                    coverage: { unread: `the alert read failed: ${messageOf(error)}` },
                }))
                .finally(close),
        close,
    }
}

export async function startAlerts(options: AlertsOptions): Promise<Alerts> {
    try {
        const { rules, excluded } = withoutExcluded(options.alerts.rules, options.alerts.exclude)
        const since = Math.floor(Date.now() / 1000)
        const engine = await startEngine(
            rules,
            options.alerts.labels,
            options.targets,
            options.scrapeIntervalMs ?? SCRAPE_INTERVAL_MS
        )
        return recordAlerts(engine, since, excluded, options)
    } catch (error) {
        const read = { lines: [], coverage: { unread: `the alert engine did not start: ${messageOf(error)}` } }
        return { finish: () => Promise.resolve(read), close: () => Promise.resolve() }
    }
}
