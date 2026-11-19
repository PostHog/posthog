import type { DashboardV2PanelApi as Panel, DashboardV2TargetApi as Target } from '../generated/api.schemas'
import { asPrevious, type DataFrame, type Field } from './frame'

type Transform = NonNullable<Panel['transforms']>[number]

function looksLikeLogs(target: Pick<Target, 'language' | 'query'>): boolean {
    if (target.language === 'logql') {
        return !!target.query.trim() && !/\b(\w+_over_time|rate|bytes_rate|rate_counter)\s*\(/.test(target.query)
    }
    if (target.language === 'hogql') {
        return (
            /\bfrom\s+logs\b/i.test(target.query) &&
            !/\bgroup\s+by\b|\b(count|sum|avg|min|max|quantile\w*|uniq\w*)\s*\(/i.test(target.query)
        )
    }
    return false
}

export type TimeSeriesShape = {
    labels: string[]
    series: { key: string; label: string; data: number[]; unit?: string }[]
}
export type CategoryShape = {
    labels: string[]
    series: { key: string; label: string; data: number[]; unit?: string }[]
    unit?: string
}

const timeField = (f: DataFrame): Field | undefined => f.fields.find((x) => x.type === 'time')
const numberFields = (f: DataFrame): Field[] => f.fields.filter((x) => x.type === 'number')
const stringFields = (f: DataFrame): Field[] => f.fields.filter((x) => x.type === 'string')

export function hasTime(frames: DataFrame[]): boolean {
    return frames.some((f) => timeField(f))
}

export function autoViz(
    frames: DataFrame[],
    t: { language: string; query: string }
): 'logs' | 'stat' | 'timeseries' | 'table' {
    if (looksLikeLogs(t as Pick<Target, 'language' | 'query'>)) {
        return 'logs'
    }
    if (
        frames.length &&
        frames.every((f) => (f.fields[0]?.values.length ?? 0) <= 1) &&
        frames.some((f) => f.fields.some((x) => x.type === 'number'))
    ) {
        return 'stat'
    }
    return hasTime(frames) ? 'timeseries' : 'table'
}

const HOUR = 3_600_000
export const monthOf = (t: number): number => {
    const d = new Date(t + 14 * HOUR)
    return d.getUTCFullYear() * 12 + d.getUTCMonth()
}
export const monthStart = (m: number): number => Date.UTC(Math.floor(m / 12), m % 12)

const gcd = (a: number, b: number): number => (b ? gcd(b, a % b) : a)
export function monthStep(times: number[]): number {
    if (times.length < 2) {
        return 0
    }
    const offs = times.map((t) => t - monthStart(monthOf(t)))
    if (offs.some((o) => Math.abs(o) > 14 * HOUR) || Math.max(...offs) - Math.min(...offs) > HOUR) {
        return 0
    }
    let k = 0
    for (let i = 1; i < times.length; i++) {
        const gap = monthOf(times[i]!) - monthOf(times[i - 1]!)
        if (gap <= 0) {
            return 0
        }
        k = gcd(k, gap)
    }
    return k
}

export function bucketEnd(times: number[]): ((t: number) => number) | undefined {
    const n = times.length
    if (n < 2) {
        return undefined
    }
    const k = monthStep(times)
    if (k) {
        return (t) => t - monthStart(monthOf(t)) + monthStart(monthOf(t) + k)
    }
    const step = times[n - 1]! - times[n - 2]!
    return step > 0 ? (t) => t + step : undefined
}

export function toTimeSeries(frames: DataFrame[], range?: { from: number; to: number }): TimeSeriesShape {
    const stamps = new Set<number>()
    for (const f of frames) {
        for (const v of timeField(f)?.values ?? []) {
            stamps.add(Number(v))
        }
    }
    let times = [...stamps].sort((a, b) => a - b)
    const counts = new Map<number, number>()
    for (const f of frames) {
        const v = (timeField(f)?.values ?? []).map(Number)
        for (let i = 1; i < v.length; i++) {
            const d = v[i]! - v[i - 1]!
            if (d > 0) {
                counts.set(d, (counts.get(d) ?? 0) + 1)
            }
        }
    }
    const step = [...counts].sort((a, b) => b[1] - a[1] || a[0] - b[0])[0]?.[0]
    const k = monthStep(times)
    if (k) {
        const first = times[0]!
        const at = (m: number): number => first - monthStart(monthOf(first)) + monthStart(m)
        let m0 = monthOf(first),
            m1 = monthOf(times[times.length - 1]!)
        for (let i = 0; range && i < 5000 && at(m0 - k) >= range.from; i++) {
            m0 -= k
        }
        for (let i = 0; range && i < 5000 && at(m1 + k) <= range.to; i++) {
            m1 += k
        }
        const slots = Array.from({ length: (m1 - m0) / k + 1 }, (_, i) => at(m0 + i * k))
        for (const t of times) {
            slots[(monthOf(t) - m0) / k] = t
        }
        return alignOn(frames, slots, (t) => (monthOf(t) - m0) / k)
    }
    const last = times[times.length - 1] ?? 0
    const first =
        step && range
            ? (times[0] ?? 0) - Math.floor(Math.max(0, (times[0] ?? 0) - range.from) / step) * step
            : (times[0] ?? 0)
    const end = step && range ? last + Math.floor(Math.max(0, range.to - last) / step) * step : last
    const n = step ? Math.round((end - first) / step) + 1 : 0
    const grid = !!step && n <= 5000
    if (grid) {
        times = Array.from({ length: n }, (_, i) => first + i * step!)
    }
    const exact = new Map(times.map((t, i) => [t, i]))
    return alignOn(frames, times, (t) => (grid ? Math.round((t - first) / step!) : exact.get(t)!))
}

function alignOn(frames: DataFrame[], times: number[], slot: (t: number) => number): TimeSeriesShape {
    const series: TimeSeriesShape['series'] = []
    frames.forEach((f, fi) => {
        const tf = timeField(f)
        if (!tf) {
            return
        }
        const nums = numberFields(f)
        nums.forEach((nf, ni) => {
            const data = new Array(times.length).fill(NaN)
            tf.values.forEach((t, i) => {
                const v = nf.values[i]
                data[slot(Number(t))] = v === null || v === undefined ? NaN : Number(v)
            })
            series.push({ key: `${fi}:${ni}`, label: seriesLabel(f, nf, nums), data, unit: nf.config?.unit })
        })
    })
    return { labels: times.map((t) => new Date(t).toISOString()), series }
}

const seriesLabel = (f: DataFrame, nf: Field, nums: Field[]): string =>
    nums.length > 1
        ? f.name && f.name !== 'value'
            ? `${f.name} ${nf.name}`
            : (nf.config?.displayName ?? nf.name)
        : (f.name ?? nf.config?.displayName ?? nf.name)

export function toCategories(frames: DataFrame[], o: { gaps?: boolean } = {}): CategoryShape {
    const first = frames[0]
    if (first && frames.every((f) => stringFields(f).length && numberFields(f).length)) {
        const labels: string[] = []
        const at = new Map<string, number>()
        for (const f of frames) {
            for (const v of stringFields(f)[0]!.values) {
                const k = String(v ?? '(none)')
                if (!at.has(k)) {
                    at.set(k, labels.length)
                    labels.push(k)
                }
            }
        }
        const series: CategoryShape['series'] = []
        frames.forEach((f, fi) => {
            const cat = stringFields(f)[0]!
            const nums = numberFields(f)
            nums.forEach((nf, ni) => {
                const data = new Array(labels.length).fill(0)
                cat.values.forEach((c, i) => {
                    const v = nf.values[i]
                    data[at.get(String(c ?? '(none)'))!] =
                        v === null || v === undefined ? (o.gaps ? NaN : 0) : Number(v)
                })
                series.push({ key: `${fi}:${ni}`, label: seriesLabel(f, nf, nums), data, unit: nf.config?.unit })
            })
        })
        return { labels, series, unit: series[0]?.unit }
    }
    const vals = frames.map((f) => reduceFrame(f, 'last'))
    return {
        labels: frames.map((f, i) => f.name ?? `series ${i + 1}`),
        series: [{ key: '0', label: 'value', data: vals.map((v) => v ?? 0) }],
        unit: numberFields(first ?? { fields: [] })[0]?.config?.unit,
    }
}

export function toXSeries(
    frames: DataFrame[],
    range?: { from: number; to: number }
): TimeSeriesShape & { categorical: boolean } {
    if (hasTime(frames)) {
        return { ...toTimeSeries(frames, range), categorical: false }
    }
    const c = toCategories(frames, { gaps: true })
    return { labels: c.labels, series: c.series, categorical: true }
}

export function alignPrevious(
    frames: DataFrame[],
    shiftMs?: number
): { frames: DataFrame[]; pairs: Map<number, number> } {
    const pairs = new Map<number, number>()
    if (!frames.some((f) => f.meta?.previous)) {
        return { frames, pairs }
    }
    const byRef = new Map<string, { cur: number[]; prev: number[] }>()
    frames.forEach((f, i) => {
        const g = byRef.get(f.refId ?? '') ?? { cur: [], prev: [] }
        ;(f.meta?.previous ? g.prev : g.cur).push(i)
        byRef.set(f.refId ?? '', g)
    })
    const out = [...frames]
    for (const { cur, prev } of byRef.values()) {
        const named = (pi: number): number | undefined => {
            const n = frames[pi]!.name?.replace(/ \(previous\)$/, '')
            return n === undefined ? undefined : cur.find((ci) => frames[ci]!.name === n)
        }
        prev.forEach((pi, k) => {
            const ci = named(pi) ?? (frames[pi]!.name === undefined ? cur[k] : undefined)
            if (ci !== undefined) {
                pairs.set(pi, ci)
            }
            const t0 = ci === undefined ? NaN : Number(timeField(frames[ci]!)?.values[0]),
                p0 = Number(timeField(frames[pi]!)?.values[0])
            const by = shiftMs !== undefined && Number.isFinite(shiftMs) ? shiftMs : t0 - p0
            if (!Number.isFinite(by)) {
                return
            }
            out[pi] = {
                ...frames[pi]!,
                fields: frames[pi]!.fields.map((x) =>
                    x.type === 'time' ? { ...x, values: x.values.map((v) => Number(v) + by) } : x
                ),
            }
        })
    }
    return { frames: out, pairs }
}

export function incompleteFrom(times: number[], asOf = Date.now()): number {
    const end = bucketEnd(times)
    return end ? times.findIndex((t) => end(t) > asOf) : -1
}

export type IncompleteMode = 'solid' | 'dashed' | 'estimate' | 'hidden'
export const incompleteMode = (panel: Pick<Panel, 'incomplete' | 'targets'>): IncompleteMode =>
    panel.incomplete ??
    (panel.targets?.some((t) => t.language === 'promql' || t.language === 'logql') ? 'solid' : 'dashed')

export function drawnIncomplete(
    panel: Pick<Panel, 'incomplete' | 'targets'>,
    frames: DataFrame[],
    times: number[]
): number {
    const mode = incompleteMode(panel)
    if (mode !== 'dashed' && mode !== 'estimate') {
        return -1
    }
    return incompleteFrom(
        times,
        Math.min(...frames.filter((f) => !f.meta?.previous).map((f) => f.meta?.asOf ?? Date.now()))
    )
}

export const frameIncomplete = (f: DataFrame): number =>
    incompleteFrom((timeField(f)?.values ?? []).map(Number), f.meta?.asOf ?? Date.now())

export function incompleteFrames(frames: DataFrame[], mode: IncompleteMode): DataFrame[] {
    if (mode !== 'hidden' && mode !== 'estimate') {
        return frames
    }
    return frames.map((f) => {
        const i = frameIncomplete(f)
        if (i < 0) {
            return f
        }
        if (mode === 'hidden') {
            return {
                ...f,
                fields: f.fields.map((x) => ({
                    ...x,
                    values: x.values.slice(0, i),
                })),
            }
        }
        const times = timeField(f)!.values.map(Number)
        const t = times[i]!
        const asOf = f.meta?.asOf ?? Date.now()
        if (t > asOf) {
            return f
        }
        const step = bucketEnd(times)!(t) - t
        const scale = step / Math.max(asOf - t, step / 10)
        return {
            ...f,
            fields: f.fields.map((x) =>
                x.type === 'number'
                    ? {
                          ...x,
                          values: x.values.map((v, j) => (j === i && typeof v === 'number' ? v * scale : v)),
                      }
                    : x
            ),
        }
    })
}

export function applyFrameTransforms(
    frames: DataFrame[],
    transforms: Transform[] = [],
    hidden: Set<string> = new Set()
): DataFrame[] {
    let out = frames
    for (const t of transforms) {
        if (t.type === 'partition') {
            out = out.flatMap((f) => partition(f, t.by))
        }
        if (t.type === 'organize') {
            out = out.map((f) =>
                f.fields.some((x) => t.fields.includes(x.name))
                    ? { ...f, fields: t.fields.flatMap((n) => f.fields.filter((x) => x.name === n)) }
                    : f
            )
        }
        if (t.type === 'math' && t.mode === 'series') {
            const prev = out.filter((f) => f.meta?.previous)
            out = [
                ...out,
                ...mathSeries(
                    t.expression,
                    t.as,
                    out.filter((f) => !f.meta?.previous)
                ),
                ...(prev.length ? asPrevious(mathSeries(t.expression, t.as, prev)) : []),
            ]
        } else if (t.type === 'math') {
            const value = evalMath(t.expression, (ref) => {
                const f = out.find((x) => x.refId === ref)
                return f ? reduceFrame(f, 'last') : null
            })
            out = [...out, { refId: t.as, name: t.as, fields: [{ name: t.as, type: 'number', values: [value] }] }]
        }
    }
    return hidden.size ? out.filter((f) => !f.refId || !hidden.has(f.refId)) : out
}

export function mathSeries(expression: string, as: string, frames: DataFrame[]): DataFrame[] {
    const refs = [...new Set([...expression.matchAll(/\$(\w+)/g)].map((m) => m[1]!))]
    const byRef = new Map(
        refs.map((ref) => {
            const series = frames
                .filter((f) => f.refId === ref)
                .flatMap((f) => {
                    const tf = timeField(f)
                    if (!tf) {
                        return []
                    }
                    const nums = numberFields(f)
                    return nums.map((nf) => ({
                        name: seriesLabel(f, nf, nums),
                        points: new Map(
                            tf.values.map((t, i) => [
                                Number(t),
                                nf.values[i] === null || nf.values[i] === undefined ? null : Number(nf.values[i]),
                            ])
                        ),
                    }))
                })
            return [ref, series] as const
        })
    )
    if (refs.some((r) => !byRef.get(r)?.length)) {
        return []
    }
    const multi = refs.filter((r) => byRef.get(r)!.length > 1)
    const names = multi.length ? [...new Set(multi.flatMap((r) => byRef.get(r)!.map((s) => s.name)))] : [undefined]
    return names.flatMap((name) => {
        const pick = (ref: string): { name: string; points: Map<number, number | null> } | undefined => {
            const ss = byRef.get(ref)!
            return ss.length === 1 ? ss[0]! : ss.find((s) => s.name === name)
        }
        const used = refs.map(pick)
        if (used.some((s) => !s)) {
            return []
        }
        const times = [...new Set(used.flatMap((s) => [...s!.points.keys()]))].sort((a, b) => a - b)
        const values = times.map((t) => evalMath(expression, (ref) => pick(ref)!.points.get(t) ?? null))
        const label = name === undefined ? as : `${as} ${name}`
        return [
            {
                refId: as,
                name: label,
                fields: [
                    { name: 'time', type: 'time' as const, values: times },
                    { name: label, type: 'number' as const, values },
                ],
            },
        ]
    })
}

export function targetsToRun(panel: { targets?: Target[]; transforms?: Transform[] }): Target[] {
    const read = new Set(
        (panel.transforms ?? []).flatMap((t) =>
            t.type === 'math' ? [...t.expression.matchAll(/\$(\w+)/g)].map((m) => m[1]!) : []
        )
    )
    return (panel.targets ?? []).filter((t) => (!t.hide || read.has(t.refId)) && t.query?.trim())
}
export const hiddenRefIds = (panel: { targets?: Target[] }): Set<string> =>
    new Set((panel.targets ?? []).filter((t) => t.hide).map((t) => t.refId))

const MATH_FNS: Record<string, (a: number[]) => number> = {
    abs: (a) => Math.abs(a[0]!),
    round: (a) => Math.round(a[0]!),
    ceil: (a) => Math.ceil(a[0]!),
    floor: (a) => Math.floor(a[0]!),
    sqrt: (a) => Math.sqrt(a[0]!),
    exp: (a) => Math.exp(a[0]!),
    log: (a) => Math.log(a[0]!),
    log10: (a) => Math.log10(a[0]!),
    min: (a) => Math.min(...a),
    max: (a) => Math.max(...a),
}
export function evalMath(expression: string, value: (ref: string) => number | null): number | null {
    const tokens = expression.match(/\$\w+|[a-z_]\w*|\d+(?:\.\d+)?(?:e[+-]?\d+)?|>=|<=|==|!=|[-+*/()<>,]|\S/gi) ?? []
    let i = 0
    const fail = (): never => {
        throw new Error('bad expression')
    }
    const atom = (): number => {
        const t = tokens[i++] ?? fail()
        if (t === '(') {
            const v = compare()
            if (tokens[i++] !== ')') {
                fail()
            }
            return v
        }
        if (t === '-') {
            return -atom()
        }
        if (t.startsWith('$')) {
            const v = value(t.slice(1))
            return v === null ? fail() : v
        }
        const fn = MATH_FNS[t.toLowerCase()]
        if (fn) {
            if (tokens[i++] !== '(') {
                fail()
            }
            const args = [compare()]
            while (tokens[i] === ',') {
                i++
                args.push(compare())
            }
            if (tokens[i++] !== ')') {
                fail()
            }
            const v = fn(args)
            return Number.isFinite(v) ? v : fail()
        }
        const n = Number(t)
        return Number.isFinite(n) ? n : fail()
    }
    const product = (): number => {
        let v = atom()
        while (tokens[i] === '*' || tokens[i] === '/') {
            const op = tokens[i++]
            const r = atom()
            v = op === '*' ? v * r : r === 0 ? fail() : v / r
        }
        return v
    }
    const sum = (): number => {
        let v = product()
        while (tokens[i] === '+' || tokens[i] === '-') {
            const op = tokens[i++]
            const r = product()
            v = op === '+' ? v + r : v - r
        }
        return v
    }
    const CMP: Record<string, (a: number, b: number) => boolean> = {
        '>': (a, b) => a > b,
        '<': (a, b) => a < b,
        '>=': (a, b) => a >= b,
        '<=': (a, b) => a <= b,
        '==': (a, b) => a === b,
        '!=': (a, b) => a !== b,
    }
    const compare = (): number => {
        let v = sum()
        while (tokens[i] && CMP[tokens[i]!]) {
            const op = tokens[i++]!
            const r = sum()
            v = CMP[op]!(v, r) ? 1 : 0
        }
        return v
    }
    try {
        const v = compare()
        return i === tokens.length ? v : null
    } catch {
        return null
    }
}
function partition(f: DataFrame, by: string): DataFrame[] {
    const key = f.fields.find((x) => x.name === by)
    if (!key) {
        return [f]
    }
    const groups = new Map<string, number[]>()
    key.values.forEach((v, i) => {
        const k = String(v ?? '(none)')
        groups.set(k, [...(groups.get(k) ?? []), i])
    })
    const rest = f.fields.filter((x) => x !== key)
    return [...groups].map(([name, idx], g) => ({
        ...f,
        name,
        fields: rest.map((x) => ({
            ...x,
            values: idx.map((i) => x.values[i]),
            ...(x.type === 'number' ? { labels: { ...x.labels, [by]: name } } : {}),
        })),
        ...(g === 0 ? {} : { meta: undefined }),
    }))
}

export type Reducer = 'last' | 'first' | 'sum' | 'mean' | 'max' | 'min' | 'count'
export function reduce(values: (number | null)[], r: Reducer): number | null {
    const xs = values.filter((v): v is number => v !== null && v !== undefined && !Number.isNaN(v))
    if (!xs.length) {
        return null
    }
    switch (r) {
        case 'first':
            return xs[0]!
        case 'sum':
            return xs.reduce((a, b) => a + b, 0)
        case 'mean':
            return xs.reduce((a, b) => a + b, 0) / xs.length
        case 'max':
            return Math.max(...xs)
        case 'min':
            return Math.min(...xs)
        case 'count':
            return xs.length
        default:
            return xs[xs.length - 1]!
    }
}
export function reduceFrame(f: DataFrame, r: Reducer): number | null {
    const nf = numberFields(f)[0]
    return nf ? reduce(nf.values as (number | null)[], r) : null
}

export type TableShape = { columns: { name: string; type: Field['type']; unit?: string }[]; rows: unknown[][] }

export function toTable(
    frames: DataFrame[],
    transforms: Transform[] = [],
    alias?: (name: string) => string[]
): TableShape {
    let shape: TableShape
    const merge = transforms.find((t) => t.type === 'merge')
    if (frames.length === 1 && !merge && !frames[0]!.fields.some((f) => f.labels && Object.keys(f.labels).length)) {
        const f = frames[0]!
        shape = {
            columns: f.fields.map((x) => ({
                name: x.config?.displayName ?? x.name,
                type: x.type,
                unit: x.config?.unit,
            })),
            rows: (f.fields[0]?.values ?? []).map((_, i) => f.fields.map((x) => x.values[i])),
        }
    } else if (merge) {
        const on = merge.on
        const byKey = new Map<string, Record<string, number | null>>()
        const cols: string[] = []
        const firstCol = frames[0]?.refId ?? frames[0]?.name ?? 'value'
        for (const f of frames) {
            const col = f.refId ?? f.name ?? 'value'
            if (!cols.includes(col)) {
                cols.push(col)
            }
            const key = numberFields(f)[0]?.labels?.[on] ?? f.name ?? ''
            if (col !== firstCol && !byKey.has(key)) {
                continue
            }
            const row = byKey.get(key) ?? {}
            row[col] = reduceFrame(f, 'last')
            byKey.set(key, row)
        }
        shape = {
            columns: [{ name: on, type: 'string' }, ...cols.map((c) => ({ name: c, type: 'number' as const }))],
            rows: [...byKey.entries()].map(([k, r]) => [k, ...cols.map((c) => r[c] ?? null)]),
        }
    } else {
        const labelKeys = [...new Set(frames.flatMap((f) => Object.keys(numberFields(f)[0]?.labels ?? {})))]
        shape = {
            columns: [
                ...(labelKeys.length
                    ? labelKeys.map((k) => ({ name: k, type: 'string' as const }))
                    : [{ name: 'series', type: 'string' as const }]),
                { name: 'value', type: 'number', unit: numberFields(frames[0] ?? { fields: [] })[0]?.config?.unit },
            ],
            rows: frames.map((f) => [
                ...(labelKeys.length ? labelKeys.map((k) => numberFields(f)[0]?.labels?.[k] ?? '') : [f.name ?? '']),
                reduceFrame(f, 'last'),
            ]),
        }
    }
    for (const t of transforms) {
        if (t.type === 'sort') {
            const ci = shape.columns.findIndex((c) => c.name === t.field || !!alias?.(c.name).includes(t.field))
            if (ci >= 0) {
                shape.rows.sort(
                    (a, b) => (Number(a[ci] ?? -Infinity) - Number(b[ci] ?? -Infinity) || 0) * (t.desc ? -1 : 1)
                )
            }
        }
        if (t.type === 'limit') {
            shape.rows = shape.rows.slice(0, t.n)
        }
        if (t.type === 'rename') {
            shape.columns = shape.columns.map((c) => (c.name === t.from ? { ...c, name: t.to } : c))
        }
    }
    return shape
}

export function namesWithVars(panel: Panel, interpolate: (s: string) => string): Panel {
    const o = panel.fieldConfig?.overrides
    if (!o || !Object.values(o).some((x) => x.displayName?.includes('$'))) {
        return panel
    }
    const overrides = Object.fromEntries(
        Object.entries(o).map(([k, x]) => [k, x.displayName ? { ...x, displayName: interpolate(x.displayName) } : x])
    )
    return { ...panel, fieldConfig: { ...panel.fieldConfig, overrides } }
}
