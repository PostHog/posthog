import type { DashboardV2BuilderStateSourceEnumApi, DashboardV2TargetLanguageEnumApi } from '../generated/api.schemas'
import type { Panel, Target } from '../spec'
import { fieldConfigFor, trendsDisplay, vizFor } from './insightViz'

export type Filter = {
    key: string
    op: FilterOp
    value: string
    values?: string[]
    resource?: boolean
}
export type FilterOp = '=' | '!=' | '=~' | '!~'
export const FILTER_OPS: FilterOp[] = ['=', '!=', '=~', '!~']

export type MetricsState = {
    metric?: string
    agg?: string
    range?: MetricRange
    window?: string
    by?: string[]
    filters?: Filter[]
    facets?: string[]
}
export type MetricRange = 'rate' | 'increase' | 'none'
export const RANGES: [MetricRange, string][] = [
    ['rate', 'Rate /s'],
    ['increase', 'Increase'],
    ['none', 'Value'],
]
export type LogsState = {
    services?: string[]
    levels?: string[]
    search?: string
    filters?: Filter[]
    mode?: LogsMode
    groupBy?: string[]
    facets?: string[]
    volumeBy?: 'service'
    order?: 'asc'
}
export type LogsMode = 'lines' | 'patterns' | 'group'
export const DEFAULT_FACETS = [
    'severity_text',
    'service_name',
    'deployment.environment.name',
    'k8s.namespace.name',
    'k8s.deployment.name',
    'k8s.pod.name',
]
export type EventsState = { insight?: InsightTarget }
export type InsightTarget = {
    query: any
    filters?: Record<string, unknown>
    variables?: Record<string, unknown>
}
export type TracesState = {
    services?: string[]
    names?: string[]
    status?: 'error' | 'ok'
    minMs?: number
    maxMs?: number
    filters?: Filter[]
    mode?: TracesMode
    order?: 'duration'
    impact?: boolean
    facets?: string[]
    volumeBy?: 'service'
    traceId?: string
}
export type TracesMode = 'traces' | 'spans' | 'operations'
export const TRACE_FACETS = [
    'service_name',
    'name',
    'deployment.environment.name',
    'k8s.namespace.name',
    'k8s.deployment.name',
    'db.system',
]
export type Builder =
    | ({ source: 'metrics' } & MetricsState)
    | ({ source: 'logs' } & LogsState)
    | ({ source: 'events' } & EventsState)
    | ({ source: 'traces' } & TracesState)

export type MetricKind = 'counter' | 'histogram' | 'gauge'
export const metricKind = (name: string): MetricKind =>
    name.endsWith('_bucket') ? 'histogram' : /_(total|count|sum)$/.test(name) ? 'counter' : 'gauge'
const QUANTILES = ['p50', 'p90', 'p95', 'p99'].map((v) => ({ value: v, label: v }))
const ACROSS = [
    { value: 'sum', label: 'sum' },
    { value: 'avg', label: 'avg' },
    { value: 'max', label: 'max' },
    { value: 'min', label: 'min' },
    { value: 'count', label: 'series count' },
    ...QUANTILES,
    { value: 'none', label: 'each series' },
]
export const AGGS: Record<MetricKind, { value: string; label: string }[]> = {
    counter: ACROSS,
    gauge: ACROSS,
    histogram: QUANTILES,
}
const aggOf = (s: MetricsState, kind: MetricKind): string =>
    AGGS[kind].some((a) => a.value === s.agg) ? s.agg! : AGGS[kind][0]!.value
export function aggLabel(s: MetricsState): string {
    const kind = metricKind(s.metric ?? '')
    const agg = AGGS[kind].find((a) => a.value === aggOf(s, kind))!.label
    const range = s.range ?? 'rate'
    return kind === 'counter' && range !== 'none' ? `${agg} of ${range}` : agg
}

const PREFERRED = [
    'container_cpu_usage_seconds_total',
    'container_memory_working_set_bytes',
    'http_requests_total',
    'up',
]
export function defaultMetric(names: string[], used: Record<string, number> = {}): string {
    const have = new Set(names)
    const top = Object.entries(used)
        .filter(([m]) => have.has(m))
        .sort((a, b) => b[1] - a[1])[0]?.[0]
    return top ?? PREFERRED.find((m) => have.has(m)) ?? names.find((m) => m.endsWith('_total')) ?? names[0]
}

const label = (k: string): string => (/^[A-Za-z_]\w*$/.test(k) ? k : `"${k}"`)
const str = (v: string): string => `"${v.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`

const reEscape = (v: string): string => v.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
function matcher(f: Filter): string | undefined {
    const vs = f.values?.length ? f.values : f.value ? [f.value] : []
    if (!f.key || !vs.length) {
        return undefined
    }
    if (vs.length === 1) {
        return `${label(f.key)}${f.op}${str(vs[0]!)}`
    }
    return `${label(f.key)}${negative(f.op) ? '!~' : '=~'}${str(vs.map(reEscape).join('|'))}`
}
export function literals(re: string): string[] | undefined {
    const alts = re.split(/(?<!\\)\|/)
    if (alts.length < 2) {
        return undefined
    }
    const lit = (a: string): boolean | '' => a && !/(?<!\\)[.*+?^${}()[\]]|\\[^.*+?^${}()|[\]\\]/.test(a)
    return alts.every(lit) ? alts.map((a) => a.replace(/\\(.)/g, '$1')) : undefined
}
export const filterValues = (f: Filter): string[] | undefined =>
    f.values?.length ? f.values : f.op === '=' || f.op === '!=' ? (f.value ? [f.value] : []) : undefined
export function valuesFilter(key: string, values: string[], negate: boolean): Filter | undefined {
    const op = negate ? '!=' : '='
    return !values.length
        ? undefined
        : values.length === 1
          ? { key, op, value: values[0]! }
          : { key, op, value: values[0]!, values }
}

export function withOp(f: Filter, op: FilterOp): Filter {
    const regex = op === '=~' || op === '!~'
    const keep = f.resource ? { resource: true } : {}
    if (regex && f.values) {
        return { key: f.key, op, value: f.values.map(reEscape).join('|'), ...keep }
    }
    const vs = !regex && (f.op === '=~' || f.op === '!~') && literals(f.value)
    return vs ? { ...valuesFilter(f.key, vs, op === '!=')!, ...keep } : { ...f, op }
}
export function toggleValue(filters: Filter[], key: string, v: string, negate: boolean): Filter[] {
    const plain = (f: Filter, neg: boolean): boolean => f.key === key && negative(f.op) === neg && !!filterValues(f)
    const out: (Filter | undefined)[] = [...filters]
    const i = filters.findIndex((f) => plain(f, negate))
    const j = filters.findIndex((f) => plain(f, !negate))
    const vs = i >= 0 ? filterValues(filters[i]!)! : []
    const mine = valuesFilter(key, vs.includes(v) ? vs.filter((x) => x !== v) : [...vs, v], negate)
    if (j >= 0) {
        out[j] = valuesFilter(
            key,
            filterValues(filters[j]!)!.filter((x) => x !== v),
            !negate
        )
    }
    if (i >= 0) {
        out[i] = mine
    } else {
        out.push(mine)
    }
    return out.filter((f): f is Filter => !!f)
}

export function selector(name: string, filters: Filter[] = []): string {
    const matchers = filters.map(matcher).filter((m): m is string => !!m)
    if (!/^[A-Za-z_:][\w:]*$/.test(name)) {
        return `{${[str(name), ...matchers].join(', ')}}`
    }
    return matchers.length ? `${name}{${matchers.join(', ')}}` : name
}

export function metricsQuery(s: MetricsState): string {
    const name = s.metric ?? ''
    const kind = metricKind(name)
    const sel = selector(name, s.filters)
    const by = (s.by ?? []).map(label)
    const agg = aggOf(s, kind)
    const w = s.window ?? '$__rate_interval'
    if (kind === 'histogram') {
        return `histogram_quantile(0.${agg.slice(1)}, sum by (${['le', ...by].join(', ')}) (rate(${sel}[${w}])))`
    }
    const range = kind === 'counter' ? (s.range ?? 'rate') : 'none'
    const inner = range === 'none' ? sel : `${range}(${sel}[${w}])`
    if (agg === 'none') {
        return inner
    }
    const [fn, arg] = /^p\d+$/.test(agg) ? ['quantile', `0.${agg.slice(1)}, `] : [agg, '']
    return by.length ? `${fn} by (${by.join(', ')}) (${arg}${inner})` : `${fn}(${arg}${inner})`
}

export function seriesCountsQuery(s: MetricsState, key: string, k = 10): string | undefined {
    if (!s.metric) {
        return undefined
    }
    const others = (s.filters ?? []).filter((f) => f.key !== key)
    const le = metricKind(s.metric) === 'histogram' ? [{ key: 'le', op: '=' as const, value: '+Inf' }] : []
    return `topk(${k}, count by (${label(key)}) (last_over_time(${selector(s.metric, [...others, ...le])}[$__range])))`
}

const builderUnit = (b?: Builder): string | undefined =>
    b?.source === 'metrics'
        ? metricUnit(b.metric)
        : b?.source === 'events' && b.insight
          ? fieldConfigFor(insightSource(b))?.unit
          : undefined
const followUnit = (p: Panel, before?: string, after?: string): string | undefined =>
    !p.fieldConfig?.unit || p.fieldConfig.unit === before ? after : p.fieldConfig.unit
const builderOverrides = (
    b?: Builder
):
    | {
          [x: string]: {
              unit?: string | undefined
              decimals?: number | undefined
              color?: string | undefined
              displayName?: string | undefined
              hidden?: boolean | undefined
              style?: 'line' | 'bars' | 'points' | undefined
              stack?: boolean | undefined
              fill?: number | undefined
              dash?: number[] | undefined
              width?: number | undefined
              axis?: 'left' | 'right' | undefined
              negate?: boolean | undefined
              cell?: 'bar' | 'color-background' | 'color-text' | undefined
              link?: string | undefined
              wrap?: boolean | undefined
              mappings?:
                  | {
                        value?: string | undefined
                        from?: number | undefined
                        to?: number | undefined
                        null?: boolean | undefined
                        text?: string | undefined
                        color?: string | undefined
                    }[]
                  | undefined
          }
      }
    | undefined => (b?.source === 'events' && b.insight ? fieldConfigFor(insightSource(b))?.overrides : undefined)
const followOverrides = (
    p: Panel,
    before?: Builder,
    after?: Builder
):
    | {
          [x: string]: {
              unit?: string | undefined
              decimals?: number | undefined
              color?: string | undefined
              displayName?: string | undefined
              hidden?: boolean | undefined
              style?: 'line' | 'bars' | 'points' | undefined
              stack?: boolean | undefined
              fill?: number | undefined
              dash?: number[] | undefined
              width?: number | undefined
              axis?: 'left' | 'right' | undefined
              negate?: boolean | undefined
              cell?: 'bar' | 'color-background' | 'color-text' | undefined
              link?: string | undefined
              wrap?: boolean | undefined
              mappings?:
                  | {
                        value?: string | undefined
                        from?: number | undefined
                        to?: number | undefined
                        null?: boolean | undefined
                        text?: string | undefined
                        color?: string | undefined
                    }[]
                  | undefined
          }
      }
    | undefined => {
    const mine = p.fieldConfig?.overrides
    return !mine || JSON.stringify(mine) === JSON.stringify(builderOverrides(before)) ? builderOverrides(after) : mine
}
export const metricUnit = (name = ''): 's' | 'By' | undefined =>
    /_seconds(_bucket)?$/.test(name) ? 's' : name.endsWith('_bytes') ? 'By' : undefined

export function metricsTargets(s: MetricsState): Target[] {
    if (!s.metric) {
        return []
    }
    return [
        {
            refId: 'A',
            language: 'promql',
            query: metricsQuery(s),
            legend: s.by?.length && s.agg !== 'none' ? s.by.map((b) => `{{${b}}}`).join(' ') : undefined,
        },
    ]
}

const sql = (v: string): string => `'${v.replace(/\\/g, '\\\\').replace(/'/g, "\\'")}'`
const attr = (k: string): string => `coalesce(nullIf(attributes[${sql(k)}], ''), resource_attributes[${sql(k)}])`

const BUCKETS =
    'time_bucket >= toStartOfInterval({date_from}, toIntervalMinute(10)) AND time_bucket <= toStartOfInterval({date_to}, toIntervalMinute(10))'

const COLUMNS: Record<string, string> = {
    service_name: 'service_name',
    severity_text: 'severity_text',
    pattern: 'pattern',
    trace_id: 'trace_id',
    span_id: 'span_id',
}

const negative = (op: FilterOp): boolean => op === '!=' || op === '!~'
const positive = (op: FilterOp): FilterOp => (op === '!=' ? '=' : op === '!~' ? '=~' : op)
const cmp = (col: string, op: FilterOp, v: string): string =>
    op === '=~' ? `match(${col}, ${sql(v)})` : op === '!~' ? `NOT match(${col}, ${sql(v)})` : `${col} ${op} ${sql(v)}`

const fps = (f: Filter, resource: boolean): string =>
    `resource_fingerprint ${negative(f.op) ? 'NOT IN' : 'IN'} (SELECT resource_fingerprint FROM log_attributes WHERE ${BUCKETS}${resource ? " AND attribute_type = 'resource'" : ''} AND attribute_key = ${sql(f.key)} AND ${cmp('attribute_value', positive(f.op), f.value)})`
const inList = (col: string, vs?: string[]): string[] => (vs?.length ? [`${col} IN (${vs.map(sql).join(', ')})`] : [])
const ERRORS = "('error', 'fatal')"

export function logsWhere(s: LogsState): string {
    const w = ['timestamp >= {date_from}', 'timestamp < {date_to}']
    if (s.services?.length) {
        w.push(`service_name IN (${s.services.map(sql).join(', ')})`)
    }
    if (s.levels?.length) {
        w.push(`severity_text IN (${s.levels.map(sql).join(', ')})`)
    }
    if (s.search?.trim()) {
        w.push(`body ILIKE ${sql(`%${s.search.trim()}%`)}`)
    }
    for (const f of s.filters ?? []) {
        if (!f.key || !f.value) {
            continue
        }
        if (COLUMNS[f.key]) {
            w.push(cmp(COLUMNS[f.key]!, f.op, f.value))
            continue
        }
        if (f.resource) {
            w.push(fps(f, true))
            continue
        }
        if (!negative(f.op)) {
            w.push(fps(f, false))
        }
        w.push(cmp(attr(f.key), f.op, f.value))
    }
    return w.join('\n  AND ')
}

function volumeBy(s: LogsState): [expr: string, alias: string] {
    if (s.volumeBy !== 'service') {
        return ['severity_text', 'level']
    }
    const top = [
        BUCKETS,
        "attribute_key = 'service.name'",
        ...inList('service_name', s.services),
        ...inList('severity_text', s.levels),
    ]
    return [
        `if(service_name IN (SELECT service_name FROM log_attributes WHERE ${top.join(' AND ')} GROUP BY service_name ORDER BY sum(attribute_count) DESC LIMIT 10), service_name, 'other')`,
        'service',
    ]
}

const alias = (k: string): string => (/^[A-Za-z_]\w*$/.test(k) ? k : `\`${k.replace(/`/g, '')}\``)

function patternsQuery(s: LogsState): string {
    if (!s.search?.trim() && !(s.filters ?? []).some((f) => f.key && f.value)) {
        const w = [
            'time_bucket >= toStartOfInterval({date_from}, toIntervalMinute(5))',
            'time_bucket < {date_to}',
            ...inList('service_name', s.services),
            ...inList('severity_text', s.levels),
        ]
        return `SELECT pattern, sum(log_count) AS logs, sumIf(log_count, severity_text IN ${ERRORS}) AS errors, arrayStringConcat(groupUniqArray(5)(service_name), ', ') AS services, max(time_bucket) AS last_seen\nFROM posthog.logs_pattern_buckets\nWHERE ${w.join('\n  AND ')}\nGROUP BY pattern\nORDER BY logs DESC\nLIMIT 200`
    }
    return `SELECT pattern, count() AS logs, countIf(severity_text IN ${ERRORS}) AS errors, arrayStringConcat(groupUniqArray(5)(service_name), ', ') AS services, max(timestamp) AS last_seen\nFROM logs\nWHERE ${logsWhere(s)}\n  AND pattern != ''\nGROUP BY pattern\nORDER BY logs DESC\nLIMIT 200`
}

function groupQuery(s: LogsState): string {
    const keys = s.groupBy?.length ? s.groupBy.slice(0, 4) : ['service_name']
    const cols = keys.map((k) => `${COLUMNS[k] ?? attr(k)} AS ${alias(k)}`)
    return `SELECT ${cols.join(', ')}, count() AS logs, countIf(severity_text IN ${ERRORS}) AS errors, max(timestamp) AS last_seen\nFROM logs\nWHERE ${logsWhere(s)}\nGROUP BY ${keys.map(alias).join(', ')}\nORDER BY logs DESC\nLIMIT 100`
}

export function facetsQuery(s: LogsState): string | undefined {
    const keys = s.facets ?? DEFAULT_FACETS
    if (!keys.length) {
        return undefined
    }
    const parts = keys.map((k) => {
        const column = k === 'severity_text' || k === 'service_name'
        const w = [
            BUCKETS,
            `attribute_key = ${sql(column ? 'service.name' : k)}`,
            ...(k === 'service_name' ? [] : inList('service_name', s.services)),
            ...(k === 'severity_text' ? [] : inList('severity_text', s.levels)),
            ...(s.filters ?? [])
                .filter(
                    (f) =>
                        f.key &&
                        f.value &&
                        f.key !== k &&
                        (f.resource || f.key === 'service_name' || f.key === 'severity_text')
                )
                .map((f) => (f.resource ? fps(f, true) : cmp(f.key, f.op, f.value))),
        ]
        return `(SELECT ${sql(k)} AS facet, ${column ? k : 'attribute_value'} AS value, sum(attribute_count) AS n, min(attribute_type = 'resource') AS resource FROM log_attributes WHERE ${w.join(' AND ')} GROUP BY value ORDER BY n DESC LIMIT 10)`
    })
    return `SELECT facet, value, n, resource FROM (\n${parts.join('\nUNION ALL\n')}\n)`
}

export function logsTargets(s: LogsState): Target[] {
    const where = logsWhere(s)
    const [by, byName] = volumeBy(s)
    return [
        {
            refId: 'A',
            language: 'hogql',
            query: `SELECT toStartOfInterval(timestamp, {interval}) AS t, ${by} AS ${byName}, count() AS logs\nFROM logs\nWHERE ${where}\nGROUP BY t, ${byName}\nORDER BY t`,
        },
        s.mode === 'patterns'
            ? {
                  refId: 'B',
                  language: 'hogql',
                  format: 'table',
                  query: patternsQuery(s),
              }
            : s.mode === 'group'
              ? {
                    refId: 'B',
                    language: 'hogql',
                    format: 'table',
                    query: groupQuery(s),
                }
              : {
                    refId: 'B',
                    language: 'hogql',
                    query: `SELECT timestamp, severity_text AS level, service_name AS service, body, attributes, resource_attributes, trace_id, span_id\nFROM logs\nWHERE ${where}\nORDER BY timestamp ${s.order === 'asc' ? 'ASC' : 'DESC'}\nLIMIT 500`,
                },
    ]
}

export const withFilter = (s: LogsState, f: Filter): LogsState =>
    withPick(s, f, { service_name: 'services', severity_text: 'levels' })
function withPick<S extends { filters?: Filter[] }>(s: S, f: Filter, lists: Record<string, keyof S>): S {
    const list = lists[f.key]
    const filters = (s.filters ?? []).filter(
        (x) => x.key !== f.key || (x.value !== f.value && !(f.op === '=' && x.op === '='))
    )
    if (list && f.op === '=') {
        return { ...s, filters, [list]: [f.value] }
    }
    return {
        ...s,
        ...(list ? { [list]: ((s[list] as string[] | undefined) ?? []).filter((v) => v !== f.value) } : {}),
        filters: [...filters, f],
    }
}

const autoTitle = (b?: Partial<Builder>): string =>
    !b?.source
        ? ''
        : b.source === 'events'
          ? insightTitle(insightSource(b as EventsState))
          : b.source === 'metrics'
            ? ((b as MetricsState).metric ?? '')
            : b.source === 'traces'
              ? (b as TracesState).traceId
                  ? `Trace ${hexId(storedId((b as TracesState).traceId!)).slice(0, 8)}`
                  : (b as TracesState).services?.length === 1
                    ? `${(b as TracesState).services![0]} traces`
                    : 'Traces'
              : (b as LogsState).services?.length === 1
                ? `${(b as LogsState).services![0]} logs`
                : 'Logs'

const generate = (b: Builder): Omit<Target, 'refId'>[] =>
    (b.source === 'events'
        ? eventsTargets(b)
        : b.source === 'logs'
          ? logsTargets(b)
          : b.source === 'traces'
            ? tracesTargets(b)
            : metricsTargets(b)
    ).map(({ refId: _r, ...t }) => t)
const languageOf = (b: Builder): Target['language'] =>
    b.source === 'events' ? 'insight' : b.source === 'logs' || b.source === 'traces' ? 'hogql' : 'promql'

const refName = (i: number): string => String.fromCharCode(65 + (i % 26)) + (i >= 26 ? Math.floor(i / 26) : '')
export function freeRefs(taken: Iterable<string>, n: number): string[] {
    const used = new Set(taken)
    const out: string[] = []
    for (let i = 0; out.length < n; i++) {
        if (!used.has(refName(i))) {
            out.push(refName(i))
        }
    }
    return out
}

export function liftBuilder(p: Panel): Panel {
    if (!p.builder) {
        return p
    }
    const { builder, ...rest } = p
    const b = builder as Builder
    const [first, ...others] = p.targets ?? []
    if (!first) {
        return {
            ...rest,
            targets: [{ refId: 'A', language: languageOf(b), query: '', builder: b }],
        }
    }
    const companions = generate(b).length - 1
    return {
        ...rest,
        targets: [
            { ...first, builder: b },
            ...others.map((t, i) => (i < companions ? { ...t, builtBy: first.refId } : t)),
        ],
    }
}

export function setTargetBuilder(panel: Panel, ref: string, b: Builder): Panel {
    const p = liftBuilder(panel)
    const ts = p.targets ?? []
    const prevT = ts.find((t) => t.refId === ref)
    const gen = generate(b)
    const spare = ts.filter((t) => t.builtBy === ref).map((t) => t.refId)
    const refs = [...spare, ...freeRefs([...ts.map((t) => t.refId), ref], gen.length)]
    const made: Target[] = gen.length
        ? gen.map((g, k) => ({
              ...g,
              refId: k === 0 ? ref : refs[k - 1]!,
              ...(prevT?.hide ? { hide: true } : {}),
              ...(k === 0 ? { builder: b } : { builtBy: ref }),
          }))
        : [
              {
                  refId: ref,
                  language: languageOf(b),
                  query: '',
                  builder: b,
                  ...(prevT?.hide ? { hide: true } : {}),
              },
          ]
    const targets = prevT
        ? ts.flatMap((t) => (t.refId === ref ? made : t.builtBy === ref ? [] : [t]))
        : [...ts, ...made]
    const next = { ...p, targets }
    if (targets[0]?.refId !== ref) {
        return next
    }
    const prev = prevT?.builder as Builder | undefined
    const title = !p.title || p.title === autoTitle(prev) ? autoTitle(b) : p.title
    if (b.source === 'logs' || b.source === 'traces') {
        return {
            ...next,
            title,
            viz: p.viz?.type === b.source ? p.viz : { type: b.source, options: {} },
        }
    }
    const unit = followUnit(p, builderUnit(prev), builderUnit(b))
    const overrides = followOverrides(p, prev, b)
    const { unit: _u, overrides: _o, ...rest } = p.fieldConfig ?? {}
    const merged = { ...rest, ...(unit ? { unit } : {}), ...(overrides ? { overrides } : {}) }
    const fieldConfig = Object.keys(merged).length ? merged : undefined
    if (b.source === 'events') {
        const vizKey = (v?: Panel['viz']): string => JSON.stringify({ type: v?.type, options: v?.options ?? {} })
        const mine =
            p.viz &&
            (prev
                ? prev.source === 'events' && !!prev.insight && vizKey(p.viz) !== vizKey(vizFor(insightSource(prev)))
                : !!prevT?.query)
        return {
            ...next,
            title,
            fieldConfig,
            viz: mine ? p.viz : vizFor(insightSource(b)),
        }
    }
    const leaving = p.viz?.type === 'logs' || p.viz?.type === 'traces' || prev?.source === 'events'
    return {
        ...next,
        title,
        fieldConfig,
        viz: leaving ? { type: 'timeseries', options: {} } : p.viz,
    }
}

export function toManual(panel: Panel, ref: string): Panel {
    const p = liftBuilder(panel)
    return {
        ...p,
        targets: (p.targets ?? []).map(({ builder, builtBy, ...t }) => ({
            ...t,
            ...(builder && t.refId !== ref ? { builder } : {}),
            ...(builtBy && builtBy !== ref ? { builtBy } : {}),
        })),
    }
}

export function logsBuilderOf(panel: Panel): { ref: string; state: LogsState } | undefined {
    const t = (liftBuilder(panel).targets ?? []).find((t) => (t.builder as Builder | undefined)?.source === 'logs')
    return t && { ref: t.refId, state: t.builder as LogsState }
}

export function editLogs(p: Panel, edit: (s: LogsState) => LogsState): Panel {
    const l = logsBuilderOf(p)
    return l ? setTargetBuilder(p, l.ref, { ...edit(l.state), source: 'logs' }) : p
}
export const addFilter = (p: Panel, f: Filter): Panel => editLogs(p, (s) => withFilter(s, f))

export function hexId(id: string): string {
    try {
        return [...atob(id)].map((c) => c.charCodeAt(0).toString(16).padStart(2, '0')).join('')
    } catch {
        return id
    }
}
export function storedId(id: string): string {
    const s = id.trim()
    return /^(?:[0-9a-f]{32}|[0-9a-f]{16})$/i.test(s)
        ? btoa(s.replace(/../g, (h) => String.fromCharCode(parseInt(h, 16))))
        : s
}
export const noId = (id: unknown): boolean => !id || /^A+=*$/.test(String(id)) || /^0+$/.test(String(id))

const SPAN_COLUMNS: Record<string, string> = {
    service_name: 'service_name',
    name: 'name',
    trace_id: 'trace_id',
    span_id: 'span_id',
    status_code: 'status_code',
}
const SPAN_RANGE = [
    'time_bucket >= toStartOfHour({date_from})',
    'time_bucket <= {date_to}',
    'timestamp >= {date_from}',
    'timestamp < {date_to}',
]
const spanAttr = (k: string): string => `coalesce(nullIf(attributes[${sql(k)}], ''), resource_attributes[${sql(k)}])`

const SPAN_BUCKETS = 'time_bucket >= toStartOfHour({date_from}) AND time_bucket <= {date_to}'
const SESSION =
    "coalesce(nullIf(attributes['session.id'], ''), nullIf(attributes['sessionId'], ''), attributes['$session_id'])"
const PERSON =
    "coalesce(nullIf(attributes['posthogDistinctId'], ''), nullIf(attributes['distinct_id'], ''), nullIf(attributes['user.id'], ''), attributes['enduser.id'])"

function spanConds(s: TracesState, except?: 'duration'): string[] {
    const w = [...inList('service_name', s.services), ...inList('name', s.names)]
    if (s.status) {
        w.push(s.status === 'error' ? 'status_code = 2' : 'status_code != 2')
    }
    if (s.minMs && except !== 'duration') {
        w.push(`duration_nano >= ${Math.round(s.minMs * 1e6)}`)
    }
    if (s.maxMs && except !== 'duration') {
        w.push(`duration_nano < ${Math.round(s.maxMs * 1e6)}`)
    }
    for (const f of s.filters ?? []) {
        if (!f.key || !f.value) {
            continue
        }
        if (SPAN_COLUMNS[f.key]) {
            w.push(cmp(SPAN_COLUMNS[f.key]!, f.op, f.value))
            continue
        }
        if (!negative(f.op)) {
            w.push(
                `resource_fingerprint IN (SELECT resource_fingerprint FROM posthog.trace_attributes WHERE ${SPAN_BUCKETS}${f.resource ? " AND attribute_type = 'span_resource_attribute'" : ''} AND attribute_key = ${sql(f.key)} AND ${cmp('attribute_value', f.op, f.value)})`
            )
        }
        if (!f.resource || negative(f.op)) {
            w.push(cmp(f.resource ? `resource_attributes[${sql(f.key)}]` : spanAttr(f.key), f.op, f.value))
        }
    }
    return w
}
const and = (w: string[]): string => w.join('\n  AND ')
export const spansWhere = (s: TracesState, except?: 'duration'): string => and([...SPAN_RANGE, ...spanConds(s, except)])

export function tracesWhere(s: TracesState): string {
    if (s.traceId) {
        return and([...SPAN_RANGE, `trace_id = ${sql(storedId(s.traceId))}`])
    }
    const conds = spanConds(s)
    if ((s.mode ?? 'traces') !== 'traces') {
        return and([...SPAN_RANGE, ...conds])
    }
    if (!conds.length) {
        return and([...SPAN_RANGE, 'is_root_span'])
    }
    const by = s.order === 'duration' ? 'duration_nano' : 'timestamp'
    return and([
        ...SPAN_RANGE,
        'is_root_span',
        `trace_id IN (SELECT trace_id FROM posthog.trace_spans WHERE ${[...SPAN_RANGE, ...conds].join(' AND ')} ORDER BY ${by} DESC LIMIT 10000)`,
    ])
}

function traceVolumeBy(s: TracesState): [expr: string, alias: string] {
    if (s.volumeBy !== 'service') {
        return ["if(status_code = 2, 'error', 'ok')", 'status']
    }
    const top = [SPAN_BUCKETS, "attribute_key = 'service.name'", ...inList('service_name', s.services)]
    return [
        `if(service_name IN (SELECT service_name FROM posthog.trace_attributes WHERE ${top.join(' AND ')} GROUP BY service_name ORDER BY sum(attribute_count) DESC LIMIT 10), service_name, 'other')`,
        'service',
    ]
}

export function tracesTargets(s: TracesState): Target[] {
    const cols =
        'timestamp, trace_id, span_id, parent_span_id, name, service_name AS service, duration_nano / 1e6 AS duration_ms, status_code'
    if (s.traceId) {
        return [
            {
                refId: 'A',
                language: 'hogql',
                format: 'table',
                query: `SELECT ${cols}, kind, attributes, resource_attributes, events\nFROM posthog.trace_spans\nWHERE ${tracesWhere(s)}\nORDER BY timestamp\nLIMIT 5000`,
            },
        ]
    }
    const mode = s.mode ?? 'traces'
    const conds = spanConds(s)
    const volume =
        mode === 'traces'
            ? conds.length
                ? `uniq(trace_id) AS traces\nFROM posthog.trace_spans\nWHERE ${spansWhere(s)}`
                : `count() AS traces\nFROM posthog.trace_spans\nWHERE ${and([...SPAN_RANGE, 'is_root_span'])}`
            : `count() AS spans\nFROM posthog.trace_spans\nWHERE ${spansWhere(s)}`
    const [by, byName] = traceVolumeBy(s)
    const pct = (q: number): string =>
        `round(quantile(${q})(duration_nano) / 1e6, 2) AS p${String(q).slice(2).padEnd(2, '0')}_ms`
    return [
        {
            refId: 'A',
            language: 'hogql',
            query: `SELECT toStartOfInterval(timestamp, {interval}) AS t, ${by} AS ${byName}, ${volume}\nGROUP BY t, ${byName}\nORDER BY t`,
        },
        mode === 'operations'
            ? {
                  refId: 'B',
                  language: 'hogql',
                  format: 'table',
                  query: `SELECT service_name AS service, name, count() AS requests, countIf(status_code = 2) AS errors, ${[0.5, 0.95, 0.99].map(pct).join(', ')}, round(sum(duration_nano) / 1e6) AS total_ms${s.impact ? `, uniqIf(${SESSION}, ${SESSION} != '') AS sessions, uniqIf(${PERSON}, ${PERSON} != '') AS people` : ''}\nFROM posthog.trace_spans\nWHERE ${spansWhere(s)}\nGROUP BY service, name\nORDER BY ${s.order === 'duration' ? 'p95_ms' : 'total_ms'} DESC\nLIMIT 200`,
              }
            : {
                  refId: 'B',
                  language: 'hogql',
                  format: 'table',
                  query: `SELECT ${cols}, attributes, resource_attributes\nFROM posthog.trace_spans\nWHERE ${tracesWhere(s)}\nORDER BY ${s.order === 'duration' ? 'duration_nano' : 'timestamp'} DESC\nLIMIT 500`,
              },
    ]
}

export const DURATION_EDGES = [0, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10_000]
export function durationsQuery(s: TracesState): string {
    const roots = (s.mode ?? 'traces') === 'traces'
    const d = 'duration_nano / 1e6'
    const b = `multiIf(${DURATION_EDGES.slice(1)
        .map((e, i) => `${d} < ${e}, ${i}`)
        .join(', ')}, ${DURATION_EDGES.length - 1})`
    return `SELECT ${b} AS bucket, count() AS n\nFROM posthog.trace_spans\nWHERE ${spansWhere(s, 'duration')}${roots ? '\n  AND is_root_span' : ''}\nGROUP BY bucket\nORDER BY bucket`
}

export function traceFacetsQuery(s: TracesState): string | undefined {
    const keys = s.facets ?? TRACE_FACETS
    if (!keys.length) {
        return undefined
    }
    const parts = keys.map((k) => {
        const w = [
            SPAN_BUCKETS,
            k === 'service_name' ? "attribute_key = 'service.name'" : `attribute_key = ${sql(k)}`,
            ...(k === 'name' ? ["attribute_type = 'span'"] : []),
            ...(k === 'service_name' ? [] : inList('service_name', s.services)),
            ...(s.filters ?? [])
                .filter((f) => f.key && f.value && f.key !== k && f.resource)
                .map(
                    (f) =>
                        `resource_fingerprint ${negative(f.op) ? 'NOT IN' : 'IN'} (SELECT resource_fingerprint FROM posthog.trace_attributes WHERE ${SPAN_BUCKETS} AND attribute_type = 'span_resource_attribute' AND attribute_key = ${sql(f.key)} AND ${cmp('attribute_value', positive(f.op), f.value)})`
                ),
        ]
        return `(SELECT ${sql(k)} AS facet, ${k === 'service_name' ? 'service_name' : 'attribute_value'} AS value, sum(attribute_count) AS n, min(attribute_type = 'span_resource_attribute') AS resource FROM posthog.trace_attributes WHERE ${w.join(' AND ')} GROUP BY value ORDER BY n DESC LIMIT 10)`
    })
    return `SELECT facet, value, n, resource FROM (\n${parts.join('\nUNION ALL\n')}\n)`
}

export const withSpanFilter = (s: TracesState, f: Filter): TracesState =>
    withPick(s, f, { service_name: 'services', name: 'names' })

export function tracesBuilderOf(panel: Panel): { ref: string; state: TracesState } | undefined {
    const t = (liftBuilder(panel).targets ?? []).find((t) => (t.builder as Builder | undefined)?.source === 'traces')
    return t && { ref: t.refId, state: t.builder as TracesState }
}
export function editTraces(p: Panel, edit: (s: TracesState) => TracesState): Panel {
    const l = tracesBuilderOf(p)
    return l ? setTargetBuilder(p, l.ref, { ...edit(l.state), source: 'traces' }) : p
}

export const tracePanel = (traceId: string): Panel =>
    applyBuilder({ title: '', viz: { type: 'traces' }, targets: [] }, { source: 'traces', traceId })
export const traceLogsPanel = (traceId: string, spanId?: string): Panel =>
    applyBuilder(
        { title: '', viz: { type: 'logs' }, targets: [] },
        {
            source: 'logs',
            order: 'asc',
            filters: [
                { key: 'trace_id', op: '=', value: traceId },
                ...(spanId ? [{ key: 'span_id', op: '=' as const, value: spanId }] : []),
            ],
        }
    )

export function withBuilderVars(p: Panel, vars: Record<string, { values: string[]; all: boolean }>): Panel {
    const valuesOf = (s: string): string[] | undefined => {
        const m = /^\$\{?(\w+)\}?$/.exec(s)
        const v = m ? vars[m[1]!] : undefined
        return v && !v.all ? v.values : undefined
    }
    const bake = (x: unknown): unknown =>
        Array.isArray(x)
            ? x.flatMap((e) => (typeof e === 'string' ? (valuesOf(e) ?? [e]) : [bake(e)]))
            : x && typeof x === 'object'
              ? Object.fromEntries(
                    Object.entries(x).map(([k, e]) => {
                        const one = typeof e === 'string' ? valuesOf(e) : undefined
                        return [k, one?.length === 1 ? one[0] : typeof e === 'string' ? e : bake(e)]
                    })
                )
              : x
    let out = liftBuilder(p)
    for (const t of out.targets ?? []) {
        const b = t.builder as Builder | undefined
        if (b && b.source !== 'events') {
            const baked = bake(b) as Builder
            if (JSON.stringify(baked) !== JSON.stringify(b)) {
                out = setTargetBuilder(out, t.refId, baked)
            }
        }
    }
    return out
}

export const applyBuilder = (p: Panel, b: Builder): Panel =>
    setTargetBuilder(p, liftBuilder(p).targets?.[0]?.refId ?? 'A', b)

export type PanelSource = 'logs' | 'traces' | 'series'
export function panelSource(p: Panel): PanelSource {
    const ts = liftBuilder(p).targets ?? []
    const first = ts[0]
    const src = (first?.builder as Builder | undefined)?.source
    return (src === 'logs' || src === 'traces') && ts.every((t) => t === first || t.builtBy === first!.refId)
        ? src
        : 'series'
}
export function withPanelSource(p: Panel, s: PanelSource): Panel {
    const l = liftBuilder(p)
    const title = l.title === autoTitle(l.targets?.[0]?.builder as Builder | undefined) ? '' : l.title
    return applyBuilder(
        { ...l, title, targets: [] },
        s === 'series'
            ? { source: 'events', insight: { query: newInsight('TrendsQuery', ['$pageview']) } }
            : { source: s }
    )
}

const same = (a: string, b: string): boolean => a.replace(/\s+/g, '') === b.replace(/\s+/g, '')
const unesc = (v: string): string => v.replace(/\\(.)/g, '$1')
const unquote = (k: string): string => (k.startsWith('"') ? unesc(k.slice(1, -1)) : k)
const labelList = (s: string): string[] =>
    s
        .split(',')
        .map((x) => unquote(x.trim()))
        .filter(Boolean)

function parseMatchers(inner: string): { name?: string; filters: Filter[] } | undefined {
    const matcher = /\s*("(?:[^"\\]|\\.)*"|[A-Za-z_][\w.]*)\s*(=~|!~|!=|=)\s*"((?:[^"\\]|\\.)*)"\s*(?:,|$)/y
    const bare = /\s*"((?:[^"\\]|\\.)*)"\s*(?:,|$)/y
    const filters: Filter[] = []
    let name: string | undefined
    const s = inner.trim()
    for (let i = 0; i < s.length; ) {
        matcher.lastIndex = bare.lastIndex = i
        const m = matcher.exec(s)
        if (m) {
            const key = unquote(m[1]!)
            if (key === '__name__' && m[2] === '=') {
                name = unesc(m[3]!)
            } else {
                filters.push({
                    key,
                    op: m[2] as FilterOp,
                    value: unesc(m[3]!),
                })
            }
            i = matcher.lastIndex
            continue
        }
        const b = bare.exec(s)
        if (!b) {
            return undefined
        }
        name = unesc(b[1]!)
        i = bare.lastIndex
    }
    return { name, filters }
}

function parseSelector(sel: string): { metric: string; filters: Filter[] } | undefined {
    const m = /^\s*([A-Za-z_:][\w:]*)?\s*(?:\{(.*)\})?\s*$/s.exec(sel)
    if (!m || (!m[1] && m[2] === undefined)) {
        return undefined
    }
    const inner = m[2] !== undefined ? parseMatchers(m[2]) : { name: undefined, filters: [] }
    const metric = m[1] ?? inner?.name
    const anyOf = (f: Filter): Filter => {
        const vs = (f.op === '=~' || f.op === '!~') && literals(f.value)
        return vs ? valuesFilter(f.key, vs, f.op === '!~')! : f
    }
    return inner && metric ? { metric, filters: inner.filters.map(anyOf) } : undefined
}

export function parseMetricsQuery(q: string): MetricsState | undefined {
    const s = q.trim()
    const fn = (x: string): RegExpExecArray | null => /^(rate|increase)\(\s*(.+?)\s*\[([^\]]+)\]\s*\)$/s.exec(x.trim())
    const win = (w: string): { window?: undefined } | { window: string } =>
        w === '$__rate_interval' ? {} : { window: w }
    const h = /^histogram_quantile\(\s*0?\.(\d+)\s*,\s*sum\s+by\s*\(([^)]*)\)\s*\((.+)\)\s*\)$/s.exec(s)
    if (h) {
        const r = fn(h[3]!)
        const sel = r?.[1] === 'rate' && parseSelector(r[2]!)
        return sel
            ? {
                  metric: sel.metric,
                  agg: `p${h[1]}`,
                  ...win(r[3]!),
                  by: labelList(h[2]!).filter((l) => l !== 'le'),
                  ...(sel.filters.length ? { filters: sel.filters } : {}),
              }
            : undefined
    }
    const AGG = '(sum|avg|max|min|count|quantile)'
    const t = new RegExp(`^${AGG}\\s*\\((.+)\\)\\s*by\\s*\\(([^)]*)\\)$`, 's').exec(s)
    const p = t ? undefined : new RegExp(`^${AGG}\\s*(?:by\\s*\\(([^)]*)\\)\\s*)?\\((.+)\\)$`, 's').exec(s)
    const [aggFn, by, arg] = t ? [t[1]!, t[3], t[2]!] : p ? [p[1]!, p[2], p[3]!] : [undefined, undefined, s]
    let inner = arg.trim()
    let agg = aggFn ?? 'none'
    if (aggFn === 'quantile') {
        const qm = /^0?\.(\d+)\s*,\s*(.+)$/s.exec(inner)
        if (!qm) {
            return undefined
        }
        agg = `p${qm[1]}`
        inner = qm[2]!
    }
    const r = fn(inner)
    const sel = parseSelector(r ? r[2]! : inner)
    if (!sel) {
        return undefined
    }
    const range = r ? (r[1] as MetricRange) : 'none'
    const kind = metricKind(sel.metric)
    return {
        metric: sel.metric,
        agg,
        ...((kind === 'counter' ? range !== 'rate' : range !== 'none') ? { range } : {}),
        ...(r ? win(r[3]!) : {}),
        ...(by ? { by: labelList(by) } : {}),
        ...(sel.filters.length ? { filters: sel.filters } : {}),
    }
}

const LEVEL_LABELS = ['level', 'severity_text', 'detected_level', 'severity']
export function parseLogsQuery(
    t: Pick<Target, 'language' | 'query'>
): { state: LogsState; complete: boolean } | undefined {
    const q = t.query.trim()
    const s: LogsState = {}
    const add = (k: 'services' | 'levels', v: string[]): string[] => (s[k] = [...(s[k] ?? []), ...v])
    if (t.language === 'logql') {
        const m = /\{([^}]*)\}((?:\s*\|=\s*"(?:[^"\\]|\\.)*")*)/.exec(q)
        const ms = m && parseMatchers(m[1]!)
        if (!m || !ms) {
            return undefined
        }
        let lost = false
        const filters: Filter[] = []
        for (const f of ms.filters) {
            const list = f.key === 'service_name' ? 'services' : LEVEL_LABELS.includes(f.key) ? 'levels' : undefined
            if (list && f.op === '=~' && /^\.[*+]$/.test(f.value)) {
                continue
            }
            if (list && (f.op === '=' || (f.op === '=~' && /^[\w.-]+(\|[\w.-]+)*$/.test(f.value)))) {
                add(list, f.value.split('|'))
                continue
            }
            if (list) {
                lost = true
            }
            filters.push(f)
        }
        if (filters.length) {
            s.filters = filters
        }
        const searches = [...(m[2] ?? '').matchAll(/"((?:[^"\\]|\\.)*)"/g)].map((x) => unesc(x[1]!))
        if (searches[0]) {
            s.search = searches[0]
        }
        return {
            state: s,
            complete: !lost && searches.length <= 1 && same(q, m[0]),
        }
    }
    if (t.language !== 'hogql' || !/\bfrom\s+logs\b/i.test(q)) {
        return undefined
    }
    const strs = (x: string): string[] => [...x.matchAll(/'((?:[^'\\]|\\.)*)'/g)].map((v) => unesc(v[1]!))
    for (const [k, col] of [
        ['services', 'service_name'],
        ['levels', 'severity_text'],
    ] as const) {
        const m = new RegExp(`\\b${col}\\s+IN\\s*\\(([^)]*)\\)|\\b${col}\\s*=\\s*('(?:[^'\\\\]|\\\\.)*')`, 'i').exec(q)
        if (m) {
            add(k, strs(m[1] ?? m[2]!))
        }
    }
    const like = /\bbody\s+I?LIKE\s+'%((?:[^'\\]|\\.)*)%'/i.exec(q)
    if (like) {
        s.search = unesc(like[1]!)
    }
    const found: [number, Filter][] = []
    for (const m of q.matchAll(
        /(NOT\s+)?match\(coalesce\(nullIf\(attributes\['((?:[^'\\]|\\.)*)'\],\s*''\),\s*resource_attributes\['(?:[^'\\]|\\.)*'\]\),\s*'((?:[^'\\]|\\.)*)'\)|coalesce\(nullIf\(attributes\['((?:[^'\\]|\\.)*)'\],\s*''\),\s*resource_attributes\['(?:[^'\\]|\\.)*'\]\)\s*(!=|=)\s*'((?:[^'\\]|\\.)*)'|\b(resource_)?attributes\['((?:[^'\\]|\\.)*)'\]\s*(!=|=)\s*'((?:[^'\\]|\\.)*)'/gi
    )) {
        if (m[2]) {
            found.push([
                m.index,
                {
                    key: unesc(m[2]),
                    op: m[1] ? '!~' : '=~',
                    value: unesc(m[3]!),
                },
            ])
        } else if (m[4]) {
            found.push([m.index, { key: unesc(m[4]), op: m[5] as FilterOp, value: unesc(m[6]!) }])
        } else {
            found.push([
                m.index,
                {
                    key: unesc(m[8]!),
                    op: m[9] as FilterOp,
                    value: unesc(m[10]!),
                    ...(m[7] ? { resource: true } : {}),
                },
            ])
        }
    }
    for (const m of q.matchAll(
        /resource_fingerprint\s+(NOT\s+)?IN\s*\(SELECT[^']*?attribute_type\s*=\s*'resource'\s+AND\s+attribute_key\s*=\s*'((?:[^'\\]|\\.)*)'\s+AND\s+(?:attribute_value\s*=\s*'((?:[^'\\]|\\.)*)'|match\(attribute_value,\s*'((?:[^'\\]|\\.)*)'\))/gi
    )) {
        found.push([
            m.index,
            {
                key: unesc(m[2]!),
                op: m[3] !== undefined ? (m[1] ? '!=' : '=') : m[1] ? '!~' : '=~',
                value: unesc(m[3] ?? m[4]!),
                resource: true,
            },
        ])
    }
    if (found.length) {
        s.filters = found.sort((a, b) => a[0] - b[0]).map(([, f]) => f)
    }
    return { state: s, complete: logsTargets(s).some((g) => same(g.query, q)) }
}

export function parseQuery(t: Pick<Target, 'language' | 'query'>): { builder: Builder; complete: boolean } | undefined {
    if (!t.query.trim()) {
        return undefined
    }
    if (t.language === 'promql') {
        const s = parseMetricsQuery(t.query)
        return (
            s && {
                builder: { ...s, source: 'metrics' },
                complete: same(metricsQuery(s), t.query),
            }
        )
    }
    if (t.language === 'insight') {
        try {
            const insight = JSON.parse(t.query) as InsightTarget
            return INSIGHT_KINDS.includes(insightSource({ insight })?.kind)
                ? { builder: { source: 'events', insight }, complete: true }
                : undefined
        } catch {
            return undefined
        }
    }
    const l = parseLogsQuery(t)
    return l && { builder: { ...l.state, source: 'logs' }, complete: l.complete }
}

export function logqlSelector(s: LogsState): string {
    const any = (k: string, vs?: string[]): string[] =>
        !vs?.length ? [] : [`${k}${vs.length === 1 ? '=' : '=~'}${str(vs.length === 1 ? vs[0]! : vs.join('|'))}`]
    const m = [
        ...any('service_name', s.services),
        ...any('level', s.levels),
        ...(s.filters ?? []).filter((f) => f.key && f.value).map((f) => `${label(f.key)}${f.op}${str(f.value)}`),
    ]
    return `{${m.length ? m.join(', ') : 'service_name=~".+"'}}${s.search?.trim() ? ` |= ${str(s.search.trim())}` : ''}`
}

export function defaultQuery(
    language: string,
    o: { builder?: Builder; metric?: string; logsViz?: boolean } = {}
): string {
    const b = o.builder
    const logs: LogsState = b?.source === 'logs' ? b : {}
    const metric = b?.source === 'metrics' && b.metric ? b.metric : (o.metric ?? 'up')
    if (language === 'promql') {
        return metricsQuery(b?.source === 'metrics' && b.metric ? b : { metric })
    }
    if (language === 'logql') {
        return o.logsViz
            ? logqlSelector(logs)
            : `sum by (service_name) (count_over_time(${logqlSelector(logs)} [$__interval]))`
    }
    if (language === 'insight') {
        return JSON.stringify(
            b?.source === 'events' && b.insight ? b.insight : { query: newInsight('TrendsQuery', ['$pageview']) },
            null,
            2
        )
    }
    if (language === 'hogql') {
        if (b?.source === 'logs' || o.logsViz) {
            return logsTargets(logs)[o.logsViz ? 1 : 0]!.query
        }
        return 'SELECT toStartOfInterval(timestamp, {interval}) AS t, count() AS events\nFROM events\nWHERE timestamp >= {date_from} AND timestamp < {date_to}\nGROUP BY t\nORDER BY t'
    }
    return `SELECT toStartOfInterval(timestamp, {interval}) AS time, avg(value) AS value\nFROM metrics\nWHERE metric_name = ${sql(metric)} AND timestamp >= {date_from} AND timestamp < {date_to}\nGROUP BY time\nORDER BY time`
}

const like = (col: string, q: string): string =>
    q.trim() ? ` AND ${col} ILIKE ${sql(`%${q.trim().replace(/[\\%_]/g, (c) => `\\${c}`)}%`)}` : ''
export const OPTIONS = {
    metrics: 'label_values(__name__)',
    labels: (metric: string) => `label_names(${selector(metric)})`,
    labelValues: (metric: string, l: string) => `label_values(${selector(metric)}, ${l})`,
    services: (q = '') =>
        `SELECT service_name FROM logs WHERE timestamp >= now() - INTERVAL 1 HOUR${like('service_name', q)} GROUP BY service_name ORDER BY count() DESC LIMIT 300`,
    levels: 'SELECT severity_text FROM logs WHERE timestamp >= now() - INTERVAL 1 HOUR GROUP BY severity_text ORDER BY count() DESC LIMIT 20',
    resourceKeys: (s: LogsState) =>
        `SELECT attribute_key AS k FROM log_attributes WHERE time_bucket >= now() - INTERVAL 1 HOUR${s.services?.length ? ` AND service_name IN (${s.services.map(sql).join(', ')})` : ''} GROUP BY k HAVING min(attribute_type = 'resource') = 1 LIMIT 1000`,
    attributeKeys: (s: LogsState, q = '') =>
        `SELECT attribute_key AS k FROM log_attributes WHERE time_bucket >= now() - INTERVAL 1 HOUR${s.services?.length ? ` AND service_name IN (${s.services.map(sql).join(', ')})` : ''}${like('attribute_key', q)} GROUP BY k ORDER BY sum(attribute_count) DESC LIMIT 300`,
    attributeValues: (s: LogsState, k: string, q = '') =>
        `SELECT attribute_value AS v FROM log_attributes WHERE time_bucket >= now() - INTERVAL 1 HOUR AND attribute_key = ${sql(k)}${s.services?.length ? ` AND service_name IN (${s.services.map(sql).join(', ')})` : ''}${like('attribute_value', q)} AND v != '' GROUP BY v ORDER BY sum(attribute_count) DESC LIMIT 200`,
    spanServices: (q = '') =>
        `SELECT service_name FROM posthog.trace_attributes WHERE ${SPAN_RECENT}${like('service_name', q)} GROUP BY service_name ORDER BY sum(attribute_count) DESC LIMIT 300`,
    spanNames: (s: TracesState, q = '') =>
        `SELECT attribute_value AS v FROM posthog.trace_attributes WHERE ${SPAN_RECENT} AND attribute_type = 'span' AND attribute_key = 'name'${inList(
            'service_name',
            s.services
        )
            .map((x) => ` AND ${x}`)
            .join('')}${like('attribute_value', q)} GROUP BY v ORDER BY sum(attribute_count) DESC LIMIT 300`,
    spanResourceKeys: (s: TracesState) =>
        `SELECT attribute_key AS k FROM posthog.trace_attributes WHERE ${SPAN_RECENT}${inList(
            'service_name',
            s.services
        )
            .map((x) => ` AND ${x}`)
            .join('')} GROUP BY k HAVING min(attribute_type = 'span_resource_attribute') = 1 LIMIT 1000`,
    spanKeys: (s: TracesState, q = '') =>
        `SELECT attribute_key AS k FROM posthog.trace_attributes WHERE ${SPAN_RECENT} AND attribute_type != 'span'${inList(
            'service_name',
            s.services
        )
            .map((x) => ` AND ${x}`)
            .join('')}${like('attribute_key', q)} GROUP BY k ORDER BY sum(attribute_count) DESC LIMIT 300`,
    spanValues: (s: TracesState, k: string, q = '') =>
        `SELECT attribute_value AS v FROM posthog.trace_attributes WHERE ${SPAN_RECENT} AND attribute_key = ${sql(k)}${inList(
            'service_name',
            s.services
        )
            .map((x) => ` AND ${x}`)
            .join(
                ''
            )}${like('attribute_value', q)} AND v != '' GROUP BY v ORDER BY sum(attribute_count) DESC LIMIT 200`,
}
const SPAN_RECENT = 'time_bucket >= toStartOfHour(now()) - INTERVAL 6 HOUR'

export const newPanel = (): Panel =>
    applyBuilder(
        { title: '', viz: { type: 'timeseries' }, targets: [] },
        {
            source: 'events',
            insight: { query: newInsight('TrendsQuery', ['$pageview']) },
        }
    )

export function newPanelFor(type: string, options: Record<string, unknown> = {}): Panel {
    const insight = (
        kind: InsightKind
    ): {
        title?: string | undefined
        description?: string | undefined
        descriptionMode?: 'hidden' | 'info' | 'below' | undefined
        hideWhenEmpty?: boolean | undefined
        viz: { type: string; options?: { [x: string]: unknown } | undefined }
        targets?:
            | {
                  refId: string
                  language: DashboardV2TargetLanguageEnumApi
                  query: string
                  legend?: string | undefined
                  bucketed?: boolean | undefined
                  instant?: boolean | undefined
                  format?: 'time_series' | 'table' | undefined
                  hide?: boolean | undefined
                  builder?: { [x: string]: unknown; source: DashboardV2BuilderStateSourceEnumApi } | undefined
                  builtBy?: string | undefined
              }[]
            | undefined
        transforms?:
            | (
                  | { type: 'partition'; by: string }
                  | { type: 'organize'; fields: string[] }
                  | { type: 'merge'; on: string }
                  | { type: 'limit'; n: number }
                  | { type: 'sort'; field: string; desc?: boolean | undefined }
                  | { type: 'rename'; from: string; to: string }
                  | { type: 'math'; as: string; expression: string; mode?: 'value' | 'series' | undefined }
              )[]
            | undefined
        fieldConfig?:
            | {
                  unit?: string | undefined
                  decimals?: number | undefined
                  min?: number | undefined
                  max?: number | undefined
                  softMin?: number | undefined
                  softMax?: number | undefined
                  thresholds?: { value: number; color: string; label?: string | undefined }[] | undefined
                  color?:
                      | {
                            mode: string
                            fixedColor?: string | undefined
                            seriesBy?: 'min' | 'max' | 'last' | 'mean' | undefined
                        }
                      | undefined
                  overrides?:
                      | {
                            [x: string]: {
                                unit?: string | undefined
                                decimals?: number | undefined
                                color?: string | undefined
                                displayName?: string | undefined
                                hidden?: boolean | undefined
                                style?: 'line' | 'bars' | 'points' | undefined
                                stack?: boolean | undefined
                                fill?: number | undefined
                                dash?: number[] | undefined
                                width?: number | undefined
                                axis?: 'left' | 'right' | undefined
                                negate?: boolean | undefined
                                cell?: 'bar' | 'color-background' | 'color-text' | undefined
                                link?: string | undefined
                                wrap?: boolean | undefined
                                mappings?:
                                    | {
                                          value?: string | undefined
                                          from?: number | undefined
                                          to?: number | undefined
                                          null?: boolean | undefined
                                          text?: string | undefined
                                          color?: string | undefined
                                      }[]
                                    | undefined
                            }
                        }
                      | undefined
                  mappings?:
                      | {
                            value?: string | undefined
                            from?: number | undefined
                            to?: number | undefined
                            null?: boolean | undefined
                            text?: string | undefined
                            color?: string | undefined
                        }[]
                      | undefined
              }
            | undefined
        cache?: { ttl?: string | undefined } | undefined
        precompute?: boolean | undefined
        interval?: string | undefined
        timeFrom?: string | undefined
        timeShift?: string | undefined
        compare?: string | undefined
        incomplete?: 'hidden' | 'solid' | 'dashed' | 'estimate' | undefined
        drilldowns?:
            | {
                  title: string
                  action:
                      | { type: 'url'; url: string; newTab?: boolean | undefined }
                      | {
                            type: 'dashboard'
                            uid: string
                            vars?: { [x: string]: string } | undefined
                            time?: 'keep' | 'clicked' | undefined
                        }
                      | { type: 'variable'; name: string; value: string }
                      | { type: 'panel'; panel: { [x: string]: unknown }; time?: 'dashboard' | 'clicked' | undefined }
                      | { readonly type: 'people' }
                      | { readonly type: 'events' }
                      | { readonly type: 'zoom' }
                      | { readonly type: 'explore' }
              }[]
            | undefined
        links?:
            | {
                  title: string
                  type?: 'link' | 'dashboards' | undefined
                  url?: string | undefined
                  tags?: string[] | undefined
                  asDropdown?: boolean | undefined
                  icon?: 'dashboard' | 'info' | 'external' | 'doc' | 'bell' | 'grafana' | 'github' | undefined
                  tooltip?: string | undefined
                  newTab?: boolean | undefined
                  keepTime?: boolean | undefined
                  includeVars?: boolean | undefined
              }[]
            | undefined
        maxDataPoints?: number | undefined
        builder?: { [x: string]: unknown; source: DashboardV2BuilderStateSourceEnumApi } | undefined
        requires?: string[] | undefined
    } =>
        applyBuilder(
            { title: '', viz: { type }, targets: [] },
            {
                source: 'events',
                ...switchKind(
                    {
                        insight: {
                            query: newInsight('TrendsQuery', ['$pageview']),
                        },
                    },
                    kind
                ),
            }
        )
    switch (type) {
        case 'logs':
        case 'traces':
            return applyBuilder({ title: '', viz: { type }, targets: [] }, { source: type })
        case 'retention':
            return insight('RetentionQuery')
        case 'sankey':
            return insight('PathsQuery')
        case 'heatmap':
            return {
                title: 'Pageviews by hour and weekday',
                viz: { type, options },
                targets: [
                    {
                        refId: 'A',
                        language: 'hogql',
                        query: "SELECT toHour(timestamp) AS hour, toDayOfWeek(timestamp) AS day, count() AS pageviews\nFROM events\nWHERE event = '$pageview' AND timestamp >= {date_from} AND timestamp < {date_to}\nGROUP BY hour, day\nORDER BY hour, day",
                    },
                ],
            }
        case 'geomap':
            return {
                title: 'Visitors by country',
                viz: { type, options },
                targets: [
                    {
                        refId: 'A',
                        language: 'hogql',
                        query: "SELECT properties.$geoip_country_code AS country, uniq(person_id) AS visitors\nFROM events\nWHERE event = '$pageview' AND timestamp >= {date_from} AND timestamp < {date_to}\nGROUP BY country\nORDER BY visitors DESC",
                        format: 'table',
                    },
                ],
            }
        case 'dashlist':
            return { title: 'Dashboards', viz: { type, options }, targets: [] }
        default:
            return withViz(newPanel(), { type, options })
    }
}

export const INSIGHT_KINDS = [
    'TrendsQuery',
    'FunnelsQuery',
    'RetentionQuery',
    'StickinessQuery',
    'LifecycleQuery',
    'PathsQuery',
]
export type InsightKind =
    | 'TrendsQuery'
    | 'FunnelsQuery'
    | 'RetentionQuery'
    | 'StickinessQuery'
    | 'LifecycleQuery'
    | 'PathsQuery'
const WRAPPERS = new Set(['InsightVizNode', 'DataVisualizationNode', 'DataTableNode'])
export const insightSource = (s: EventsState): any =>
    WRAPPERS.has(s.insight?.query?.kind) ? s.insight!.query.source : s.insight?.query
export function withSource(s: EventsState, src: any): EventsState {
    const q = s.insight?.query
    return {
        ...s,
        insight: {
            ...s.insight,
            query: WRAPPERS.has(q?.kind) ? { ...q, source: src } : src,
        },
    }
}

export const actionPick = (id: number | string, name: string): string => `action:${id}:${name}`
export const parseAction = (e: string | null | undefined): { id: number; name: string } | undefined => {
    const m = e ? /^action:(\d+):(.*)$/s.exec(e) : null
    return m ? { id: Number(m[1]), name: m[2]! } : undefined
}
export const eventNode = (
    event: string | null,
    math?: string
):
    | { math?: string | undefined; kind: string; id: number; name: string }
    | { math?: string | undefined; kind: string; event: string | null; name: string } => {
    const a = parseAction(event)
    return {
        ...(a
            ? { kind: 'ActionsNode', id: a.id, name: a.name }
            : { kind: 'EventsNode', event, name: event ?? 'All events' }),
        ...(math ? { math } : {}),
    }
}
const entity = (
    event: string | null
): { id: number; name: string; type: string } | { id: string | null; name: string; type: string } => {
    const a = parseAction(event)
    return a ? { id: a.id, name: a.name, type: 'actions' } : { id: event, name: event ?? 'All events', type: 'events' }
}
const pickOf = (n: any): string | null =>
    n?.kind === 'ActionsNode' || n?.type === 'actions'
        ? actionPick(n.id, n.name ?? `Action ${n.id}`)
        : (n?.event ?? (n?.type === 'events' ? n.id : null) ?? null)
export function insightEvents(src: any): (string | null)[] {
    if (src?.kind === 'RetentionQuery') {
        return [pickOf(src.retentionFilter?.targetEntity), pickOf(src.retentionFilter?.returningEntity)]
    }
    if (src?.kind === 'PathsQuery') {
        return pathEvents(src)
    }
    return (src?.series ?? []).map(pickOf)
}

export function newInsight(kind: InsightKind, events: (string | null)[], from?: any): any {
    const ev = events.length ? events : ['$pageview']
    const keep = {
        ...(from?.properties?.length ? { properties: from.properties } : {}),
        ...(from?.filterTestAccounts ? { filterTestAccounts: true } : {}),
    }
    const bd = from?.breakdownFilter ? { breakdownFilter: from.breakdownFilter } : {}
    const interval = from?.interval ?? 'day'
    switch (kind) {
        case 'FunnelsQuery':
            return {
                kind,
                series: (ev.length > 1 ? ev : [ev[0]!, ev[0]!]).map((e) => eventNode(e)),
                funnelsFilter: {
                    funnelVizType: 'steps',
                    funnelOrderType: 'ordered',
                    funnelWindowInterval: 14,
                    funnelWindowIntervalUnit: 'day',
                },
                ...keep,
                ...bd,
            }
        case 'RetentionQuery':
            return {
                kind,
                retentionFilter: {
                    targetEntity: entity(ev[0]!),
                    returningEntity: entity(ev[1] ?? ev[0]!),
                    period: 'Week',
                    totalIntervals: 8,
                    retentionType: 'retention_first_time',
                },
                ...keep,
            }
        case 'PathsQuery':
            return {
                kind,
                pathsFilter: {
                    includeEventTypes: ['$pageview'],
                    stepLimit: 5,
                    edgeLimit: 50,
                },
                ...keep,
            }
        case 'LifecycleQuery':
            return { kind, series: [eventNode(ev[0]!)], interval, ...keep }
        case 'StickinessQuery':
            return {
                kind,
                series: ev.map((e) => eventNode(e)),
                interval,
                ...keep,
            }
        default:
            return {
                kind: 'TrendsQuery',
                series: ev.map((e) => eventNode(e, 'total')),
                interval,
                trendsFilter: { display: 'ActionsLineGraph' },
                ...keep,
                ...bd,
            }
    }
}

export function switchKind(s: EventsState, kind: InsightKind): EventsState {
    const src = insightSource(s)
    const next = withSource(s, newInsight(kind, insightEvents(src), src))
    const { date_from: _f, date_to: _t, ...rest } = next.insight!.filters ?? {}
    const filters = kind === 'RetentionQuery' ? { ...rest, date_from: null, date_to: null } : rest
    return {
        ...next,
        insight: {
            ...next.insight!,
            filters: Object.keys(filters).length ? filters : undefined,
        },
    }
}

export function withViz(p: Panel, viz: Panel['viz']): Panel {
    const display = trendsDisplay(viz)
    let next: Panel = { ...p, viz }
    for (const t of p.targets ?? []) {
        const b = t.builder as Builder | undefined
        const src = b?.source === 'events' ? insightSource(b) : undefined
        if (src?.kind !== 'TrendsQuery' || (src.trendsFilter?.display ?? 'ActionsLineGraph') === display) {
            continue
        }
        const nb: Builder = {
            ...withSource(b as EventsState, {
                ...src,
                trendsFilter: { ...src.trendsFilter, display },
            }),
            source: 'events',
        }
        next = setTargetBuilder(next, t.refId, nb)
        const unit =
            t.refId === p.targets?.[0]?.refId ? followUnit(p, builderUnit(b), builderUnit(nb)) : p.fieldConfig?.unit
        const { unit: _u, ...rest } = next.fieldConfig ?? {}
        next = {
            ...next,
            viz,
            fieldConfig: unit ? { ...rest, unit } : Object.keys(rest).length ? rest : undefined,
        }
    }
    return next
}

export function setInsightEvent(src: any, i: number, event: string | null): any {
    if (src.kind === 'RetentionQuery') {
        return {
            ...src,
            retentionFilter: {
                ...src.retentionFilter,
                [i ? 'returningEntity' : 'targetEntity']: entity(event),
            },
        }
    }
    return {
        ...src,
        series: src.series.map((n: any, j: number) => {
            if (j !== i) {
                return n
            }
            const { kind: _k, event: _e, id: _i, name: _n, custom_name: _c, ...keep } = n
            return { ...keep, ...eventNode(event) }
        }),
    }
}

export const PATH_TYPES: [string, string][] = [
    ['$pageview', 'Pageviews'],
    ['$screen', 'Screens'],
    ['custom_event', 'Events'],
]
export function pathEvents(src: any): (string | null)[] {
    const types: string[] = src?.pathsFilter?.includeEventTypes ?? ['$pageview']
    return types.includes('custom_event') ? [] : types
}
export function pathPointOptions(src: any): {
    query: string
    search: (q: string) => string
} {
    const type = (src?.pathsFilter?.includeEventTypes ?? ['$pageview'])[0]
    if (type === 'custom_event') {
        return { query: EVENT_OPTIONS.events(), search: EVENT_OPTIONS.events }
    }
    const key = type === '$screen' ? '$screen_name' : '$current_url'
    return {
        query: EVENT_OPTIONS.values([type], key),
        search: (q) => EVENT_OPTIONS.values([type], key, q),
    }
}

export function eventsTargets(s: EventsState): Target[] {
    return s.insight?.query
        ? [
              {
                  refId: 'A',
                  language: 'insight',
                  query: JSON.stringify(s.insight, null, 2),
              },
          ]
        : []
}

const pretty = (e: string | null): string =>
    parseAction(e)
        ? parseAction(e)!.name
        : e == null
          ? 'All events'
          : e === '$pageview'
            ? 'Pageviews'
            : e === '$screen'
              ? 'Screens'
              : e === '$autocapture'
                ? 'Autocapture'
                : e.replace(/^\$/, '')
export function insightTitle(src: any): string {
    const ev = insightEvents(src)
    if (!src) {
        return ''
    }
    if (src.kind === 'FunnelsQuery') {
        return ev.map(pretty).join(' → ')
    }
    if (src.kind === 'RetentionQuery') {
        return `${pretty(ev[0]!)} retention`
    }
    if (src.kind === 'LifecycleQuery') {
        return `${pretty(ev[0]!)} lifecycle`
    }
    if (src.kind === 'StickinessQuery') {
        return `${ev.map(pretty).join(', ')} stickiness`
    }
    if (src.kind === 'PathsQuery') {
        const f = src.pathsFilter ?? {}
        return f.startPoint ? `Paths from ${f.startPoint}` : f.endPoint ? `Paths to ${f.endPoint}` : 'User paths'
    }
    return ev.map(pretty).join(', ')
}

const hql = (v: string): string => `'${v.replace(/\\/g, '\\\\').replace(/'/g, "\\'")}'`
const onEvents = (events: (string | null)[]): string => {
    const e = events.filter((x): x is string => !!x)
    return e.length && e.length === events.length && !e.some(parseAction)
        ? ` AND event IN (${e.map(hql).join(', ')})`
        : ''
}
export const EVENT_OPTIONS = {
    events: (q = '') =>
        `SELECT event, count() AS n FROM events WHERE timestamp >= now() - INTERVAL 7 DAY${like('event', q)} GROUP BY event ORDER BY n DESC LIMIT 300`,
    properties: (events: (string | null)[], q = '') =>
        `SELECT k FROM (SELECT properties FROM events WHERE timestamp >= now() - INTERVAL 1 DAY${onEvents(events)} LIMIT 20000) ARRAY JOIN JSONExtractKeys(properties) AS k${q.trim() ? ` WHERE 1${like('k', q)}` : ''} GROUP BY k ORDER BY count() DESC LIMIT 300`,
    values: (events: (string | null)[], key: string, q = '') =>
        `SELECT JSONExtractString(properties, ${hql(key)}) AS v FROM events WHERE timestamp >= now() - INTERVAL 1 DAY${onEvents(events)}${like('v', q)} AND v != '' GROUP BY v ORDER BY count() DESC LIMIT 200`,
}

export type PropKind = 'event' | 'person'
const valueExpr = (kind: PropKind, key: string): string =>
    kind === 'person'
        ? `toString(person.properties[${hql(key)}])`
        : `replaceRegexpAll(JSONExtractRaw(properties, ${hql(key)}), '^"|"$', '')`
const sample = (kind: PropKind, events: (string | null)[], conds: string[] = [], limit = 20000): string => {
    const scope = onEvents(events) + conds.map((c) => ` AND ${c}`).join('')
    return `events WHERE timestamp >= now() - INTERVAL ${kind === 'person' && !scope ? '1 HOUR' : '1 DAY'}${scope} LIMIT ${limit}`
}
export const propCondition = (kind: PropKind, key: string, value: string): string =>
    `${valueExpr(kind, key)} = ${hql(value)}`
export const isFlagKey = (k: string): boolean => k.startsWith('$feature/') || k.startsWith('$feature_enrollment/')
export const PROPERTY_QUERIES = {
    eventKeys: (events: (string | null)[], q = '', conds: string[] = []) =>
        `SELECT k AS prop_key, count() AS n, (SELECT count() FROM (SELECT 1 FROM ${sample('event', events, conds)})) AS total FROM (SELECT properties FROM ${sample('event', events, conds)}) ARRAY JOIN JSONExtractKeys(properties) AS k${q.trim() ? ` WHERE 1${like('k', q)}` : ''} GROUP BY k ORDER BY n DESC LIMIT 5000`,
    personKeys: (events: (string | null)[] = [], conds: string[] = []) =>
        `SELECT k AS prop_key, count() AS n, (SELECT count() FROM (SELECT 1 FROM ${sample('person', events, conds, 5000)})) AS total FROM (SELECT person.properties AS p FROM ${sample('person', events, conds, 5000)}) ARRAY JOIN JSONExtractKeys(p) AS k GROUP BY k ORDER BY n DESC LIMIT 5000`,
    definitions: (kind: PropKind, q = '', names?: string[]) =>
        `SELECT name AS prop_key, property_type AS prop_type FROM system.property_definitions WHERE type = ${hql(kind)}${names?.length ? ` AND name IN (${names.map(hql).join(', ')})` : q.trim() ? '' : " AND NOT startsWith(name, '$feature')"}${like('name', q)} ORDER BY startsWith(name, '$'), name LIMIT 500`,
    values: (kind: PropKind, key: string, events: (string | null)[], q = '', conds: string[] = []) =>
        `SELECT v AS prop_value, count() AS n, (SELECT count() FROM (SELECT 1 FROM ${sample(kind, events, conds)})) AS total FROM (SELECT ${valueExpr(kind, key)} AS v FROM ${sample(kind, events, conds)}) WHERE isNotNull(v) AND v != ''${like('v', q)} GROUP BY v ORDER BY n DESC LIMIT 50`,
    stats: (kind: PropKind, key: string, events: (string | null)[], conds: string[] = []) =>
        `SELECT min(x) AS prop_min, quantile(0.5)(x) AS median, max(x) AS max, avg(x) AS mean, count() AS n FROM (SELECT toFloatOrNull(${valueExpr(kind, key)}) AS x FROM ${sample(kind, events, conds)}) WHERE isNotNull(x)`,
    cohorts: () =>
        'SELECT id AS cohort_id, name, count, is_static FROM system.cohorts WHERE NOT deleted ORDER BY count DESC LIMIT 500',
    actions: () =>
        'SELECT id AS action_id, name, description FROM system.actions WHERE NOT deleted ORDER BY name LIMIT 500',
}

export type LogCondition = { key: string; value: string }
const logWhere = (service: string | undefined, conds: LogCondition[]): string =>
    [
        'time_bucket >= now() - INTERVAL 1 HOUR',
        ...(service ? [`service_name = ${hql(service)}`] : []),
        ...conds.map((c) =>
            c.key === 'severity_text'
                ? `severity_text = ${hql(c.value)}`
                : `resource_fingerprint IN (SELECT resource_fingerprint FROM log_attributes WHERE time_bucket >= now() - INTERVAL 1 HOUR AND attribute_key = ${hql(c.key)} AND attribute_value = ${hql(c.value)})`
        ),
    ].join(' AND ')
const logLines = (service: string | undefined, conds: LogCondition[]): string =>
    `(SELECT sum(attribute_count) FROM log_attributes WHERE ${logWhere(service, conds)} AND attribute_key = 'service.name')`
export const INTROSPECT_QUERIES = {
    events: () =>
        'SELECT event AS entity, count() AS n FROM events WHERE timestamp >= now() - INTERVAL 7 DAY GROUP BY event ORDER BY n DESC LIMIT 1000',
    logServices: () =>
        "SELECT service_name AS entity, sum(attribute_count) AS n FROM log_attributes WHERE time_bucket >= now() - INTERVAL 1 HOUR AND attribute_key = 'service.name' GROUP BY entity ORDER BY n DESC LIMIT 1000",
    logKeys: (service: string | undefined, conds: LogCondition[]) =>
        `SELECT attribute_key AS prop_key, sum(attribute_count) AS n, min(attribute_type = 'resource') AS resource, ${logLines(service, conds)} AS total FROM log_attributes WHERE ${logWhere(service, conds)} GROUP BY prop_key ORDER BY n DESC LIMIT 300`,
    logValues: (service: string | undefined, key: string, conds: LogCondition[], q = '') =>
        key === 'severity_text'
            ? `SELECT severity_text AS prop_value, sum(attribute_count) AS n, ${logLines(service, conds)} AS total FROM log_attributes WHERE ${logWhere(service, conds)} AND attribute_key = 'service.name'${like('severity_text', q)} GROUP BY prop_value ORDER BY n DESC LIMIT 50`
            : `SELECT attribute_value AS prop_value, sum(attribute_count) AS n, ${logLines(service, conds)} AS total FROM log_attributes WHERE ${logWhere(service, conds)} AND attribute_key = ${hql(key)}${like('attribute_value', q)} GROUP BY prop_value ORDER BY n DESC LIMIT 50`,
}
