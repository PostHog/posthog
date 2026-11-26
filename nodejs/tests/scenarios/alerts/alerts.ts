import { readFileSync } from 'fs'
import { parse, stringify } from 'yaml'

import { Engine, ScrapeTarget, startEngine } from './engine'
import { selectorsOf } from './selectors'

const SCRAPE_INTERVAL_MS = 5000

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

type VmRule = { name: string; query: string; lastError: string }

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
    const { expr } = await engine.metrics('/expand-with-exprs', { query, format: 'json' })
    const missing = []
    for (const selector of selectorsOf(expr)) {
        const end = `${Math.ceil(Date.now() / 1000)}`
        const { data } = await engine.metrics('/api/v1/series', {
            'match[]': selector,
            start: `${since}`,
            end,
            limit: '1',
        })
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
        const { data } = await engine.alerting('/api/v1/rules', { type: 'alert' })
        const rules = (data.groups as { rules: VmRule[] }[]).flatMap((group) => group.rules)
        const lines: RuleLine[] = []
        for (const { name: rule, query, lastError } of rules) {
            const selectors = await missingSelectorsOf(engine, query, since)
            lines.push(
                selectors.length > 0 || lastError
                    ? { type: 'rule', rule, state: 'unevaluable', selectors, ...(lastError && { error: lastError }) }
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
