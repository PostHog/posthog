import type { DashboardV2PanelApi as Panel } from '../generated/api.schemas'
import { colorToken, thresholdColor } from './chartCommon'
import { reduce, type Reducer } from './frames'

export type ColorKind = 'palette' | 'by-name' | 'fixed' | 'shades' | 'thresholds' | 'continuous'
export type Scheme = { mode: string; label: string; kind: ColorKind; colors?: string[]; hint?: string }

const GREEN = '#2f9e44',
    AMBER = '#e8a317',
    ORANGE = '#e8590c',
    RED = '#d6336c',
    BLUE = '#1c7ed6'
const GRAFANA = [
    '#73bf69',
    '#f2cc0c',
    '#8ab8ff',
    '#ff780a',
    '#f2495c',
    '#5794f2',
    '#b877d9',
    '#705da0',
    '#37872d',
    '#fade2a',
]
const MUTED = ['#6b8fb8', '#c48a5a', '#7fa57a', '#b56d7c', '#8d7bb5', '#c2a35a', '#5f9ea0', '#a07a9e']

export const SCHEMES: Scheme[] = [
    { mode: 'palette-classic', label: 'Classic', kind: 'palette', hint: 'A colour per series, in order' },
    {
        mode: 'palette-classic-by-name',
        label: 'By name',
        kind: 'by-name',
        hint: 'The same series gets the same colour on every panel',
    },
    { mode: 'palette-grafana', label: 'Grafana', kind: 'palette', colors: GRAFANA },
    { mode: 'palette-muted', label: 'Muted', kind: 'palette', colors: MUTED },
    { mode: 'fixed', label: 'Single colour', kind: 'fixed', hint: 'Every series one colour' },
    { mode: 'shades', label: 'Shades', kind: 'shades', hint: 'Light to dark shades of one colour' },
    {
        mode: 'thresholds',
        label: 'From thresholds',
        kind: 'thresholds',
        hint: 'Each series coloured by its value against the thresholds',
    },
    { mode: 'continuous-GrYlRd', label: 'Green–Yellow–Red', kind: 'continuous', colors: [GREEN, AMBER, ORANGE, RED] },
    { mode: 'continuous-RdYlGr', label: 'Red–Yellow–Green', kind: 'continuous', colors: [RED, ORANGE, AMBER, GREEN] },
    { mode: 'continuous-BlYlRd', label: 'Blue–Yellow–Red', kind: 'continuous', colors: [BLUE, AMBER, RED] },
    { mode: 'continuous-YlRd', label: 'Yellow–Red', kind: 'continuous', colors: ['#f2cc0c', ORANGE, RED] },
    { mode: 'continuous-blues', label: 'Blues', kind: 'continuous', colors: ['#a5d8ff', BLUE, '#0b3d91'] },
    { mode: 'continuous-greens', label: 'Greens', kind: 'continuous', colors: ['#b2f2bb', GREEN, '#1b5e20'] },
    { mode: 'continuous-reds', label: 'Reds', kind: 'continuous', colors: ['#ffc9c9', RED, '#8b1a3a'] },
    { mode: 'continuous-purples', label: 'Purples', kind: 'continuous', colors: ['#e5dbff', '#7950f2', '#3b1f8f'] },
]
export const schemeOf = (mode?: string): Scheme => SCHEMES.find((s) => s.mode === mode) ?? SCHEMES[0]!
export const DEFAULT_SCHEME = 'palette-classic-by-name'

const NAME_POOL = [0, 1, 2, 4, 5, 6]

function nameSlots(labels: string[], n: number): Map<string, number> {
    const pool = n > Math.max(...NAME_POOL) ? NAME_POOL : Array.from({ length: n }, (_, i) => i)
    const rest = Array.from({ length: n }, (_, i) => i).filter((i) => !pool.includes(i))
    const out = new Map<string, number>()
    const used = new Set<number>()
    for (const l of [...new Set(labels)].sort()) {
        const h = hash(l)
        let slot: number | undefined
        for (let k = 0; k < pool.length && slot === undefined; k++) {
            const c = pool[(h + k) % pool.length]!
            slot = used.has(c) ? undefined : c
        }
        slot ??= rest.find((c) => !used.has(c)) ?? h % n
        used.add(slot)
        out.set(l, slot)
    }
    return out
}

const hex = (c: string): [number, number, number] | undefined => {
    const m = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(c.trim())
    if (!m) {
        return undefined
    }
    const h = m[1]!.length === 3 ? [...m[1]!].map((x) => x + x).join('') : m[1]!
    return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)) as [number, number, number]
}
const toHex = (rgb: number[]): string =>
    '#' +
    rgb
        .map((v) =>
            Math.round(Math.max(0, Math.min(255, v)))
                .toString(16)
                .padStart(2, '0')
        )
        .join('')
const mix = (a: string, b: string, t: number): string => {
    const x = hex(a),
        y = hex(b)
    return x && y ? toHex(x.map((v, i) => v + (y[i]! - v) * t)) : a
}
export function along(stops: string[], t: number): string {
    if (stops.length === 1) {
        return stops[0]!
    }
    const p = Math.max(0, Math.min(1, t)) * (stops.length - 1)
    const i = Math.min(stops.length - 2, Math.floor(p))
    return mix(stops[i]!, stops[i + 1]!, p - i)
}
const hash = (s: string): number => {
    let h = 5381
    for (let i = 0; i < s.length; i++) {
        h = ((h << 5) + h + s.charCodeAt(i)) | 0
    }
    return Math.abs(h)
}

export function colorize<S extends { label: string; data: (number | null)[]; color?: string }>(
    panel: Panel,
    series: S[],
    palette: string[]
): (S & { color: string })[] {
    const c = panel.fieldConfig?.color
    const scheme = schemeOf(c?.mode ?? DEFAULT_SCHEME)
    const fixed = colorToken(c?.fixedColor ?? 'blue')
    const by = (c?.seriesBy ?? 'last') as Reducer
    const values =
        scheme.kind === 'thresholds' || scheme.kind === 'continuous' ? series.map((s) => reduce(s.data, by)) : []
    let lo = Infinity,
        hi = -Infinity
    if (values.length) {
        for (const x of series) {
            for (const v of x.data) {
                if (v !== null && Number.isFinite(v)) {
                    lo = Math.min(lo, v)
                    hi = Math.max(hi, v)
                }
            }
        }
    }
    lo = panel.fieldConfig?.min ?? lo
    hi = panel.fieldConfig?.max ?? hi
    const colors = scheme.colors ?? palette
    const exact = (s: S): boolean => !!panel.fieldConfig?.overrides?.[s.label]?.color
    const family = new Map<string, number>()
    for (const s of series) {
        if (s.color?.startsWith('#') && !exact(s)) {
            family.set(s.color, (family.get(s.color) ?? 0) + 1)
        }
    }
    const slots =
        scheme.kind === 'by-name' && series.length > 1
            ? nameSlots(
                  series.filter((s) => !s.color).map((s) => s.label),
                  colors.length
              )
            : undefined
    const nth = new Map<string, number>()
    const shade = (s: S): string => {
        const n = family.get(s.color!) ?? 0
        if (n < 2 || exact(s)) {
            return s.color!
        }
        const k = nth.get(s.color!) ?? 0
        nth.set(s.color!, k + 1)
        return mix(s.color!, '#ffffff', (k / (n - 1)) * 0.55)
    }
    return series.map((s, i) => {
        if (s.color) {
            return { ...s, color: shade(s) }
        }
        const v = values[i] ?? null
        const color =
            scheme.kind === 'by-name'
                ? colors[slots?.get(s.label) ?? 0]!
                : scheme.kind === 'fixed'
                  ? fixed
                  : scheme.kind === 'shades'
                    ? mix(fixed, '#ffffff', series.length > 1 ? (i / (series.length - 1)) * 0.65 : 0)
                    : scheme.kind === 'thresholds'
                      ? (thresholdColor(v, panel) ?? colors[i % colors.length]!)
                      : scheme.kind === 'continuous'
                        ? v === null
                            ? colors[0]!
                            : along(colors, hi > lo ? (v - lo) / (hi - lo) : 1)
                        : colors[i % colors.length]!
        return { ...s, color }
    })
}

export function schemeColor(
    panel: Panel,
    label: string,
    data: (number | null)[],
    palette: string[]
): string | undefined {
    return panel.fieldConfig?.color?.mode ? colorize(panel, [{ label, data }], palette)[0]!.color : undefined
}

export const defaultMode = (vizType?: string): 'thresholds' | 'fixed' | 'palette-classic-by-name' =>
    vizType === 'table' ? 'thresholds' : vizType === 'heatmap' ? 'fixed' : DEFAULT_SCHEME
export const byValue = (mode?: string): boolean => mode === 'thresholds' || schemeOf(mode).kind === 'continuous'

export function valueColor(panel: Panel, v: number | null, lo: number, hi: number): string | undefined {
    if (v === null || !Number.isFinite(v)) {
        return undefined
    }
    const scheme = schemeOf(panel.fieldConfig?.color?.mode)
    if (scheme.kind !== 'continuous') {
        return thresholdColor(v, panel)
    }
    const a = panel.fieldConfig?.min ?? lo,
        b = panel.fieldConfig?.max ?? hi
    return along(scheme.colors!, b > a ? (v - a) / (b - a) : 1)
}
