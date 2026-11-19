import type { DashboardV2MappingApi as Mapping, DashboardV2PanelApi as Panel } from '../generated/api.schemas'
import type { Display } from '../spec'
import { dtf, formatValue } from './format'
import type { DataFrame } from './frame'
import { hasTime, monthOf, monthStart, monthStep, reduce, reduceFrame, toXSeries, type Reducer } from './frames'

const SPACIOUS_OPTIONS: Record<string, Record<string, unknown>> = {
    timeseries: { area: true, gradient: true, lineWidth: 2 },
    stat: { colorMode: 'none', sparkline: true, sparklineFill: true, showChange: true },
    pie: { donut: true },
}
export function withDisplayDefaults(display: Display, type: string | undefined, options: unknown): unknown {
    const defaults = display === 'spacious' && type ? SPACIOUS_OPTIONS[type] : undefined
    return defaults ? { ...defaults, ...(options as object | undefined) } : options
}

export function yAxisFor(
    panel: Panel,
    unit?: string | null
): { tickFormatter: (v: number) => string; min: number | undefined; max: number | undefined; startAtZero: boolean } {
    const fc = panel.fieldConfig
    const u = fc?.unit ?? unit
    return {
        tickFormatter: (v: number) => formatValue(v, u, fc?.decimals),
        min: fc?.min ?? undefined,
        max: fc?.max ?? undefined,
        startAtZero: fc?.min == null ? true : fc.min === 0,
    }
}
export function tooltipFor(
    panel: Panel,
    unit?: string | null
): { valueFormatter: (v: number) => string; sortedByValue: boolean; showTotal: boolean } {
    const u = panel.fieldConfig?.unit ?? unit
    return {
        valueFormatter: (v: number) => formatValue(v, u, panel.fieldConfig?.decimals),
        sortedByValue: true,
        showTotal: false,
    }
}
export function goalLinesFor(
    panel: Panel,
    stroke: 'dashed' | 'solid' = 'dashed'
): { value: number; label: string; color: string; stroke: 'dashed' | 'solid' }[] {
    return (panel.fieldConfig?.thresholds ?? [])
        .filter((t) => t.value > 0)
        .map((t) => ({
            value: t.value,
            label: t.label || formatValue(t.value, panel.fieldConfig?.unit),
            color: colorToken(t.color),
            stroke,
        }))
}
export function thresholdBands(panel: Panel): { from: number; to: number; color: string }[] {
    const ts = [...(panel.fieldConfig?.thresholds ?? [])].sort((a, b) => a.value - b.value)
    return ts.map((t, i) => ({ from: t.value, to: ts[i + 1]?.value, color: colorToken(t.color) }))
}
export function colorToken(c: string): string {
    const map: Record<string, string> = {
        green: '#2f9e44',
        amber: '#e8a317',
        orange: '#e8590c',
        red: '#d6336c',
        blue: '#1c7ed6',
        gray: '#868e96',
        grey: '#868e96',
    }
    return map[c] ?? c
}
export const panelBackground = (c: string, solid: boolean): string =>
    solid ? c : `linear-gradient(120deg, color-mix(in oklab, ${c} 80%, black), color-mix(in oklab, ${c} 80%, white))`
export function thresholdColor(v: number | null, panel: Panel): string | undefined {
    const ts = panel.fieldConfig?.thresholds
    if (v === null || !ts?.length) {
        return undefined
    }
    let color: string | undefined
    for (const t of [...ts].sort((a, b) => a.value - b.value)) {
        if (v >= t.value) {
            color = colorToken(t.color)
        }
    }
    return color
}
type Override = NonNullable<NonNullable<Panel['fieldConfig']>['overrides']>[string]
const regexCache = new Map<string, RegExp | null>()
const regexOf = (key: string): RegExp => {
    if (!regexCache.has(key)) {
        const m = /^\/(.*)\/([a-z]*)$/.exec(key)
        let re: RegExp | null = null
        try {
            if (m) {
                re = new RegExp(m[1]!, m[2]!.replace('g', ''))
            }
        } catch {}
        regexCache.set(key, re)
    }
    return regexCache.get(key)!
}
export function fieldOverride(panel: Panel, name: string, position?: number): Override | undefined {
    const all = panel.fieldConfig?.overrides
    if (!all) {
        return undefined
    }
    let out: Override | undefined
    let current = name
    for (const [key, o] of Object.entries(all)) {
        const re = regexOf(key)
        if (!re || !re.test(current)) {
            continue
        }
        if (o.displayName) {
            current = /\$\d/.test(o.displayName) ? current.replace(re, o.displayName) : o.displayName
        }
        out = Object.assign(out ?? {}, o, o.displayName ? { displayName: current } : {})
    }
    const at = position === undefined ? undefined : all[`#${position}`]
    if (at) {
        out = { ...out, ...at }
        if (at.displayName) {
            current = at.displayName
        }
    }
    if (all[name]) {
        out = { ...out, ...all[name] }
        if (all[name].displayName) {
            current = all[name].displayName
        }
    }
    if (current !== name && all[current]) {
        out = { ...out, ...all[current], displayName: all[current].displayName ?? current }
    }
    return out
}
export function withOverrides<S extends { label: string; pos?: number }>(
    panel: Panel,
    series: S[]
): (S & { color?: string; o?: Override })[] {
    if (!panel.fieldConfig?.overrides) {
        return series
    }
    return series.flatMap((s, i) => {
        const o = fieldOverride(panel, s.label, s.pos ?? i)
        if (o?.hidden) {
            return []
        }
        return [
            {
                ...s,
                label: o?.displayName ?? s.label,
                ...(o?.color ? { color: colorToken(o.color) } : {}),
                ...(o ? { o } : {}),
            },
        ]
    })
}
export function mapValue(
    panel: Panel,
    v: number | string | null | undefined,
    own?: Mapping[] | null
): { text?: string; color?: string } | undefined {
    for (const m of [...(own ?? []), ...(panel.fieldConfig?.mappings ?? [])]) {
        const isNull = v === null || v === undefined || (typeof v === 'number' && Number.isNaN(v))
        const hit = m.null
            ? isNull
            : m.value != null
              ? !isNull && String(v) === m.value
              : (m.from != null || m.to != null) &&
                !isNull &&
                Number(v) >= (m.from ?? -Infinity) &&
                Number(v) <= (m.to ?? Infinity)
        if (hit) {
            return { text: m.text ?? undefined, color: m.color ? colorToken(m.color) : undefined }
        }
    }
    return undefined
}

function intervalFromLabels(labels: string[]): 'second' | 'minute' | 'hour' | 'day' | 'week' | 'month' {
    if (labels.length < 2) {
        return 'hour'
    }
    const step = (new Date(labels[1]!).getTime() - new Date(labels[0]!).getTime()) / 1000
    if (step < 60) {
        return 'second'
    }
    if (step < 3600) {
        return 'minute'
    }
    if (step < 86400) {
        return 'hour'
    }
    if (step < 7 * 86400) {
        return 'day'
    }
    if (step < 31 * 86400) {
        return 'week'
    }
    return 'month'
}

export function xAxisFor(
    labels: string[],
    tz?: string
): {
    interval: 'second' | 'minute' | 'hour' | 'day' | 'week' | 'month'
    tickFormatter: (v: string) => string
    labelFormatter: (v: string) => string
} {
    if (!labels.every((l) => /^\d{4}-\d\d/.test(l) && !Number.isNaN(Date.parse(l)))) {
        return { interval: intervalFromLabels([]), tickFormatter: (v: string) => v, labelFormatter: (v: string) => v }
    }
    const times = labels.map(Date.parse)
    const k = monthStep(times)
    const interval = k ? 'month' : intervalFromLabels(labels)
    const span = times.length ? times[times.length - 1]! - times[0]! : 0
    const multiDay = span > 36 * 3600 * 1000
    const hmIn = (z: string | undefined, t: number): string =>
        dtf('hm', z, { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(t)
    const dayZone =
        (interval === 'day' || interval === 'week') &&
        !times.every((t) => hmIn(tz, t) === '00:00') &&
        times.every((t) => hmIn('UTC', t) === '00:00')
            ? 'UTC'
            : tz
    const years = new Set(times.map((t) => Math.floor(monthOf(t) / 12)))
    const monthFmt = dtf(k % 12 === 0 ? 'axis-y' : years.size > 1 ? 'axis-my' : 'axis-m', 'UTC', {
        ...(k % 12 === 0 || years.size > 1 ? { year: 'numeric' } : {}),
        ...(k % 12 === 0 ? {} : { month: 'short' }),
    })
    const fmt = (v: string): string => {
        const t = Date.parse(v)
        if (Number.isNaN(t)) {
            return v
        }
        if (k) {
            return monthFmt.format(monthStart(monthOf(t)))
        }
        if (interval === 'day' || interval === 'week' || interval === 'month') {
            return dtf('md', dayZone, { month: 'short', day: 'numeric' }).format(t)
        }
        const md = dtf('md', tz, { month: 'short', day: 'numeric' }).format(t)
        return multiDay ? `${md} ${hmIn(tz, t)}` : hmIn(tz, t)
    }
    return { interval, tickFormatter: (v: string) => fmt(v), labelFormatter: fmt }
}

export function reduceParts(
    panel: Panel,
    frames: DataFrame[],
    reducer: Reducer
): {
    name: string
    value: number | null
    data: number[]
    labels: string[]
    categorical: boolean
    unit: string | undefined
    color: string | undefined
}[] {
    if (!frames.length) {
        return []
    }
    if (
        hasTime(frames) ||
        frames.every((f) => f.fields.some((x) => x.type === 'string') && f.fields.some((x) => x.type === 'number'))
    ) {
        const { series, labels, categorical } = toXSeries(frames)
        return withOverrides(panel, series).map((s) => ({
            name: s.label,
            value: reduce(s.data, reducer),
            data: s.data,
            labels,
            categorical,
            unit: s.o?.unit ?? s.unit,
            color: s.color,
        }))
    }
    return withOverrides(
        panel,
        frames.map((f) => ({ label: f.name ?? '', f }))
    ).map(({ label, f, color }) => ({
        name: label,
        value: reduceFrame(f, reducer),
        data: [] as number[],
        labels: [] as string[],
        categorical: false,
        unit: f.fields.find((x) => x.type === 'number')?.config?.unit,
        color,
    }))
}
