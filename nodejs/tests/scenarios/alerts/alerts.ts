import { readFileSync } from 'fs'
import { setTimeout as sleep } from 'timers/promises'
import { parse, stringify } from 'yaml'
import { z } from 'zod'

import type { AlertsProfile } from '../cards/schema'
import type { ValveTimelineEntry } from '../valves/valves'
import { Engine, ScrapeTarget, startEngine } from './engine'
import { selectorsOf } from './selectors'

const POLL_MS = 5000
const SCRAPE_INTERVAL_MS = 5000
const NEVER_EVALUATED = 'vmalert did not evaluate it during the run'
const THRESHOLD = /(>=|<=|==|!=|>|<)\s*(?:bool\s+)?(-?[0-9.]+(?:e[+-]?[0-9]+)?)\s*$/i

export type AlertState = 'pending' | 'firing' | 'resolved'

export type AlertTransition = {
    at: number
    rule: string
    tier?: string
    labels: Record<string, string>
    state: AlertState
    value: number | null
    threshold?: { op: string; value: number }
    for: number
    runbook?: string
}

type RuleLine =
    | { type: 'rule'; rule: string; state: 'evaluated'; fired: boolean }
    | { type: 'rule'; rule: string; state: 'unevaluable'; selectors: string[]; error?: string }
    | { type: 'rule'; rule: string; state: 'excluded' }

type Since = { sinceDriveMs: number; sinceValves: { valve: string; target: string; sinceMs: number }[] }

export type AlertLine = ({ type: 'transition' } & AlertTransition & Since) | RuleLine

export type AlertCoverage =
    | {
          evaluated: string[]
          fired: string[]
          unevaluable: { rule: string; selectors: string[]; error?: string }[]
          excluded: string[]
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
    finish(drive: { startedAt: number }, timeline: readonly ValveTimelineEntry[]): Promise<AlertsRead>
    close(): Promise<void>
}

const Labels = z.record(z.string(), z.string())
const VmAlert = z.object({ state: z.enum(['pending', 'firing']), value: z.string(), labels: Labels })
const VmRule = z.object({
    name: z.string(),
    query: z.string(),
    duration: z.number(),
    lastError: z.string(),
    lastEvaluation: z.string(),
    labels: Labels.optional(),
    annotations: Labels.optional(),
    alerts: z.array(VmAlert).nullish(),
})
const VmRules = z.object({ data: z.object({ groups: z.array(z.object({ rules: z.array(VmRule) })) }) })
const Expanded = z.object({ expr: z.string() })
const Series = z.object({ data: z.array(z.unknown()) })
type VmAlert = z.infer<typeof VmAlert>
type VmRule = z.infer<typeof VmRule>

const messageOf = (error: unknown): string => (error instanceof Error ? error.message : String(error))

function withoutExcluded(file: string, exclude: string[]): { rules: string; excluded: string[] } {
    const { groups } = parse(readFileSync(file, 'utf8')) as { groups: { rules: { alert?: string }[] }[] }
    const left = (alert?: string): boolean => alert !== undefined && exclude.includes(alert)
    return {
        rules: stringify({
            groups: groups.map((group) => ({ ...group, rules: group.rules.filter(({ alert }) => !left(alert)) })),
        }),
        excluded: groups.flatMap(({ rules }) => rules.flatMap(({ alert }) => (left(alert) ? [alert!] : []))),
    }
}

function transitionOf(rule: VmRule, alert: VmAlert, state: AlertState): AlertTransition {
    const value = Number(alert.value)
    const threshold = THRESHOLD.exec(rule.query)
    return {
        at: Date.now(),
        rule: rule.name,
        ...(rule.labels?.severity !== undefined && { tier: rule.labels.severity }),
        labels: alert.labels,
        state,
        value: Number.isFinite(value) ? value : null,
        ...(threshold && { threshold: { op: threshold[1], value: Number(threshold[2]) } }),
        for: rule.duration,
        ...(rule.annotations?.runbook_url !== undefined && { runbook: rule.annotations.runbook_url }),
    }
}

async function missingSelectorsOf(engine: Engine, query: string, since: number): Promise<string[]> {
    const { expr } = Expanded.parse(await engine.metrics('/expand-with-exprs', { query, format: 'json' }))
    const missing = []
    for (const selector of selectorsOf(expr)) {
        const end = `${Math.ceil(Date.now() / 1000)}`
        const { data } = Series.parse(
            await engine.metrics('/api/v1/series', { 'match[]': selector, start: `${since}`, end, limit: '1' })
        )
        if (data.length === 0) {
            missing.push(selector)
        }
    }
    return missing
}

function coverageOf(lines: RuleLine[]): AlertCoverage {
    const named = (state: RuleLine['state']): string[] =>
        lines.flatMap((line) => (line.state === state ? [line.rule] : []))
    return {
        evaluated: named('evaluated'),
        fired: lines.flatMap((line) => (line.state === 'evaluated' && line.fired ? [line.rule] : [])),
        unevaluable: lines.flatMap((line) =>
            line.state === 'unevaluable'
                ? [{ rule: line.rule, selectors: line.selectors, ...(line.error && { error: line.error }) }]
                : []
        ),
        excluded: named('excluded'),
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

function recordAlerts(engine: Engine, since: number, excluded: string[], options: AlertsOptions): Alerts {
    const transitions: AlertTransition[] = []
    const errors = new Map<string, string>()
    const open = new Map<string, { rule: VmRule; alert: VmAlert }>()
    let rules: VmRule[] = []
    const record = (transition: AlertTransition): void => {
        transitions.push(transition)
        options.onTransition(transition)
    }
    const read = async (): Promise<void> => {
        const { data } = VmRules.parse(await engine.alerting('/api/v1/rules', { type: 'alert' }))
        rules = data.groups.flatMap((group) => group.rules)
        const seen = new Set<string>()
        for (const rule of rules) {
            if (rule.lastError) {
                errors.set(rule.name, rule.lastError)
            }
            for (const alert of rule.alerts ?? []) {
                const key = JSON.stringify([rule.name, Object.entries(alert.labels).sort()])
                seen.add(key)
                if (open.get(key)?.alert.state !== alert.state) {
                    record(transitionOf(rule, alert, alert.state))
                }
                open.set(key, { rule, alert })
            }
        }
        for (const [key, { rule, alert }] of open) {
            if (!seen.has(key)) {
                open.delete(key)
                record(transitionOf(rule, alert, 'resolved'))
            }
        }
    }
    const stopped = new AbortController()
    const polling = (async () => {
        while (!stopped.signal.aborted) {
            await read().catch(() => undefined)
            await sleep(options.pollMs ?? POLL_MS, undefined, { signal: stopped.signal }).catch(() => undefined)
        }
    })()
    let closed: Promise<void> | undefined
    const close = (): Promise<void> =>
        (closed ??= (async () => {
            stopped.abort()
            await polling
            await engine.stop()
        })())
    const finish = async (
        drive: { startedAt: number },
        timeline: readonly ValveTimelineEntry[]
    ): Promise<AlertsRead> => {
        stopped.abort()
        await polling
        await read()
        const fired = new Set(transitions.filter(({ state }) => state === 'firing').map(({ rule }) => rule))
        const ruleLines: RuleLine[] = []
        for (const { name: rule, query, lastEvaluation } of rules) {
            const selectors = await missingSelectorsOf(engine, query, since)
            const error = errors.get(rule) ?? (Date.parse(lastEvaluation) >= since * 1000 ? undefined : NEVER_EVALUATED)
            ruleLines.push(
                selectors.length > 0 || error !== undefined
                    ? { type: 'rule', rule, state: 'unevaluable', selectors, ...(error && { error }) }
                    : { type: 'rule', rule, state: 'evaluated', fired: fired.has(rule) }
            )
        }
        ruleLines.push(...excluded.map((rule): RuleLine => ({ type: 'rule', rule, state: 'excluded' })))
        const lines: AlertLine[] = [
            ...transitions.map((transition) => ({
                type: 'transition' as const,
                ...transition,
                ...sinceOf(transition.at, drive, timeline),
            })),
            ...ruleLines,
        ]
        return { lines, coverage: coverageOf(ruleLines) }
    }
    return {
        finish: (drive, timeline) =>
            finish(drive, timeline)
                .catch((error: unknown) => ({
                    lines: [],
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
