import { readFileSync } from 'fs'
import { parse, stringify } from 'yaml'
import { z } from 'zod'

import { Engine, ScrapeTarget, startEngine } from './engine'
import { readsOf } from './selectors'

const SCRAPE_INTERVAL_MS = 5000
const NEVER_EVALUATED = 'vmalert did not evaluate it during the run'

export type AlertRules = { rules: string; labels: string; exclude: string[] }

type RuleLine =
    | { type: 'rule'; rule: string; state: 'evaluated' }
    | { type: 'rule'; rule: string; state: 'unevaluable'; selectors: string[]; error?: string }
    | { type: 'rule'; rule: string; state: 'excluded' }

export type AlertLine = RuleLine

export type AlertCoverage =
    | {
          evaluated: string[]
          unevaluable: { rule: string; selectors: string[]; error?: string }[]
          excluded: string[]
      }
    | { unread: string }

export type AlertsRead = { lines: AlertLine[]; coverage: AlertCoverage }

export type AlertsOptions = { alerts: AlertRules; targets: ScrapeTarget[]; scrapeIntervalMs?: number }

export interface Alerts {
    finish(): Promise<AlertsRead>
    close(): Promise<void>
}

const VmRule = z.object({ name: z.string(), query: z.string(), lastError: z.string(), lastEvaluation: z.string() })
const VmRules = z.object({ data: z.object({ groups: z.array(z.object({ rules: z.array(VmRule) })) }) })
const Expanded = z.object({ expr: z.string() })
const Series = z.object({ data: z.array(z.unknown()) })

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

function coverageOf(lines: RuleLine[]): AlertCoverage {
    const named = (state: RuleLine['state']): string[] =>
        lines.flatMap((line) => (line.state === state ? [line.rule] : []))
    return {
        evaluated: named('evaluated'),
        unevaluable: lines.flatMap((line) =>
            line.state === 'unevaluable'
                ? [{ rule: line.rule, selectors: line.selectors, ...(line.error && { error: line.error }) }]
                : []
        ),
        excluded: named('excluded'),
    }
}

function recordAlerts(engine: Engine, since: number, excluded: string[]): Alerts {
    let closed: Promise<void> | undefined
    const close = (): Promise<void> => (closed ??= engine.stop())
    const finish = async (): Promise<AlertsRead> => {
        const { data } = VmRules.parse(await engine.alerting('/api/v1/rules', { type: 'alert' }))
        const rules = data.groups.flatMap((group) => group.rules)
        const lines: RuleLine[] = []
        for (const { name: rule, query, lastError, lastEvaluation } of rules) {
            const selectors = await missingSelectorsOf(engine, query, since)
            const error = lastError || (Date.parse(lastEvaluation) >= since * 1000 ? undefined : NEVER_EVALUATED)
            lines.push(
                selectors.length > 0 || error
                    ? { type: 'rule', rule, state: 'unevaluable', selectors, ...(error && { error }) }
                    : { type: 'rule', rule, state: 'evaluated' }
            )
        }
        lines.push(...excluded.map((rule): RuleLine => ({ type: 'rule', rule, state: 'excluded' })))
        return { lines, coverage: coverageOf(lines) }
    }
    return {
        finish: () =>
            finish()
                .catch((error: unknown) => ({
                    lines: [],
                    coverage: { unread: `the alert read failed: ${messageOf(error)}` },
                }))
                .finally(close),
        close,
    }
}

export async function startAlerts({
    alerts,
    targets,
    scrapeIntervalMs = SCRAPE_INTERVAL_MS,
}: AlertsOptions): Promise<Alerts> {
    try {
        const { rules, excluded } = withoutExcluded(alerts.rules, alerts.exclude)
        const since = Math.floor(Date.now() / 1000)
        return recordAlerts(await startEngine(rules, alerts.labels, targets, scrapeIntervalMs), since, excluded)
    } catch (error) {
        const read = { lines: [], coverage: { unread: `the alert engine did not start: ${messageOf(error)}` } }
        return { finish: () => Promise.resolve(read), close: () => Promise.resolve() }
    }
}
