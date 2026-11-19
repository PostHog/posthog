import type { DataFrame } from '../charts/frame'
import type { Target } from '../spec'
import {
    SAMPLE_ACTIONS,
    SAMPLE_COHORTS,
    SAMPLE_EVENT_PROPERTIES,
    SAMPLE_EVENTS,
    SAMPLE_PERSON_PROPERTIES,
    type SampleEvent,
    type SampleProperty,
} from './sampleEvents'
import { portions, type SampleAttributeRow } from './sampleInfra'
import { SAMPLE_LOG_ATTRIBUTES } from './sampleLogs'
import { SAMPLE_METRIC_NAMES, sampleSeries, type SampleLabels } from './sampleMetrics'
import { SAMPLE_SPANS, SAMPLE_TRACE_ATTRIBUTES, spanResourceAttributes } from './sampleTraces'
import { SAMPLE_METRIC_USAGE, SAMPLE_USAGE } from './sampleUsage'
import { useQuery, type QueryResult as Lookup } from './useQuery'
import type { ResolvedVars } from './variables'

export interface QueryInput {
    signal?: AbortSignal
    projectId: number | string
    target: Target
    time: { from: string; to: string }
    variables: ResolvedVars
    minInterval?: string
    maxDataPoints?: number
}

export interface QueryResult {
    frames: DataFrame[]
    error?: string
}

export interface Usage {
    dashboards: number
    metrics: Record<string, number>
    labels: Record<string, number>
    values: Record<string, Record<string, number>>
    services: Record<string, number>
    attributes: Record<string, number>
}

export const pj = (projectId: string | number): string => `/api/projects/${projectId}`

export async function api<T>(path: string, init?: { method?: string; body?: string }): Promise<T> {
    const [route, search = ''] = path.split('?')
    if (route.endsWith('/variables/options')) {
        const request: { variable?: { language?: string; query?: string }; search?: string } = JSON.parse(
            init?.body ?? '{}'
        )
        return sampleOptions(request.variable?.language, request.variable?.query ?? '', request.search) as T
    }
    if (route.endsWith('/usage')) {
        const metric = new URLSearchParams(search).get('metric')
        return (metric ? { labels: SAMPLE_METRIC_USAGE[metric] ?? {} } : SAMPLE_USAGE) as T
    }
    return {} as T
}

export async function runQuery({ target }: QueryInput): Promise<QueryResult> {
    if (target.language === 'promql') {
        return { frames: seriesCountFrames(target.query) }
    }
    if (target.language === 'hogql') {
        const table = TABLES.find(({ marker }) => target.query.includes(marker))
        return { frames: table ? [tableFrame(table.columns, table.rows(target.query))] : [] }
    }
    return { frames: [] }
}

export const useUsage = (projectId: string): Lookup<Usage> =>
    useQuery({
        queryKey: ['usage', projectId],
        staleTime: 5 * 60_000,
        queryFn: () => api<Usage>(`${pj(projectId)}/usage`),
    })

export const useMetricUsage = (projectId: string, metric?: string): Lookup<{ labels: Record<string, number> }> =>
    useQuery({
        queryKey: ['usage', projectId, metric],
        enabled: !!metric,
        staleTime: 5 * 60_000,
        queryFn: () =>
            api<{ labels: Record<string, number> }>(
                `${pj(projectId)}/usage?metric=${encodeURIComponent(metric ?? '')}`
            ),
    })

type Counted = [value: string, count: number][]
type Rows = unknown[][]

const TEXT = "(?:[^'\\\\]|\\\\.)*"
const unescape = (text: string): string => text.replace(/\\(.)/g, '$1')
const has = (value: string, search: string): boolean => !search || value.toLowerCase().includes(search)

function listOf(sql: string, column: string): string[] | undefined {
    const list = new RegExp(`(?<![\\w.])${column} IN \\(('${TEXT}'(?:, '${TEXT}')*)\\)`).exec(sql)
    if (list) {
        return [...list[1].matchAll(new RegExp(`'(${TEXT})'`, 'g'))].map((match) => unescape(match[1]))
    }
    const one = new RegExp(`(?<![\\w.])${column} = '(${TEXT})'`).exec(sql)
    return one ? [unescape(one[1])] : undefined
}

function searchOf(sql: string): string {
    const match = new RegExp(`ILIKE '%(${TEXT})%'`).exec(sql)
    return match ? unescape(unescape(match[1])).toLowerCase() : ''
}

function pattern(source: string, anchored: boolean): (value: string) => boolean {
    try {
        const regex = new RegExp(anchored ? `^(?:${source})$` : source)
        return (value) => regex.test(value)
    } catch {
        return () => false
    }
}

function tally<T>(items: T[], key: (item: T) => string, amount: (item: T) => number): Counted {
    const sums = new Map<string, number>()
    for (const item of items) {
        sums.set(key(item), (sums.get(key(item)) ?? 0) + amount(item))
    }
    return [...sums].sort((a, b) => b[1] - a[1])
}

function tableFrame(columns: string[], rows: Rows): DataFrame {
    return {
        fields: columns.map((name, column) => ({
            name,
            type: typeof rows[0]?.[column] === 'number' ? 'number' : 'string',
            values: rows.map((row) => row[column]),
        })),
    }
}

const MATCHER = /("(?:[^"\\]|\\.)*"|[A-Za-z_][\w.]*)\s*(=~|!~|!=|=)\s*"((?:[^"\\]|\\.)*)"/g
const unquote = (label: string): string => (label.startsWith('"') ? unescape(label.slice(1, -1)) : label.trim())

function inOrder(a: string, b: string): number {
    const [x, y] = [a, b].map((value) => (value === '+Inf' ? Infinity : Number(value)))
    return Number.isNaN(x) || Number.isNaN(y) ? a.localeCompare(b) : x - y
}

function seriesMatching(selector: string): SampleLabels[] {
    const parsed = /^\s*([A-Za-z_:][\w:]*)?\s*(?:\{(.*)\})?\s*$/s.exec(selector)
    const inner = parsed?.[2] ?? ''
    const quoted = /^\s*"((?:[^"\\]|\\.)*)"\s*(?:,|$)/.exec(inner)
    const metric = parsed?.[1] ?? (quoted ? unescape(quoted[1]) : undefined)
    if (!metric) {
        return []
    }
    const tests = [...inner.matchAll(MATCHER)].map(([, label, operator, raw]) => {
        const key = unquote(label)
        const value = unescape(raw)
        const matches = operator.includes('~') ? pattern(value, true) : (candidate: string) => candidate === value
        return (labels: SampleLabels) => matches(labels[key] ?? '') !== operator.startsWith('!')
    })
    return sampleSeries(metric).filter((labels) => tests.every((test) => test(labels)))
}

function metricOptions(query: string): string[] {
    if (query === 'label_values(__name__)') {
        return SAMPLE_METRIC_NAMES
    }
    const names = /^label_names\((.*)\)$/s.exec(query)
    if (names) {
        return [...new Set(seriesMatching(names[1]).flatMap((labels) => Object.keys(labels)))]
    }
    const values = /^label_values\((.*),\s*("(?:[^"\\]|\\.)*"|[\w.]+)\s*\)$/s.exec(query)
    if (values) {
        const label = unquote(values[2])
        const found = new Set(seriesMatching(values[1]).map((labels) => labels[label]))
        return [...found].filter((value) => value !== undefined).sort(inOrder)
    }
    return []
}

function seriesCountFrames(query: string): DataFrame[] {
    const counts = /^topk\((\d+), count by \((.+?)\) \(last_over_time\((.*)\[\$__range\]\)\)\)$/s.exec(query)
    if (!counts) {
        return []
    }
    const label = unquote(counts[2])
    const carrying = seriesMatching(counts[3]).filter((labels) => labels[label] !== undefined)
    return tally(
        carrying,
        (labels) => labels[label],
        () => 1
    )
        .slice(0, Number(counts[1]))
        .map(([value, count]) => ({
            fields: [
                { name: 'Time', type: 'time', values: [Date.now()] },
                { name: 'Value', type: 'number', values: [count], labels: { [label]: value } },
            ],
        }))
}

const FINGERPRINT = new RegExp(
    `resource_fingerprint (NOT )?IN \\(SELECT resource_fingerprint FROM \\S+ WHERE .*?attribute_key = '(${TEXT})' AND (?:attribute_value = '(${TEXT})'|match\\(attribute_value, '(${TEXT})'\\))\\)`,
    'g'
)

const attributeIndex = (sql: string): SampleAttributeRow[] =>
    sql.includes('trace_attributes') ? SAMPLE_TRACE_ATTRIBUTES : SAMPLE_LOG_ATTRIBUTES

function scoped(sql: string, index = attributeIndex(sql)): SampleAttributeRow[] {
    const rest = sql.replace(FINGERPRINT, '')
    const services = listOf(rest, 'service_name')
    const levels = listOf(rest, 'severity_text')
    let rows = index.filter(
        (row) => (!services || services.includes(row.service)) && (!levels || levels.includes(row.level))
    )
    for (const [, excluded, rawKey, exact, regex] of sql.matchAll(FINGERPRINT)) {
        const key = unescape(rawKey)
        const matches =
            exact === undefined ? pattern(unescape(regex), false) : (candidate: string) => candidate === unescape(exact)
        const having = new Set(index.filter((row) => row.key === key && matches(row.value)).map((row) => row.resource))
        rows = rows.filter((row) => having.has(row.resource) !== !!excluded)
    }
    return rows
}

function attributeKey(sql: string): string | undefined {
    const keys = [...sql.replace(FINGERPRINT, '').matchAll(new RegExp(`attribute_key = '(${TEXT})'`, 'g'))]
    return keys.length ? unescape(keys[keys.length - 1][1]) : undefined
}

const lines = (rows: SampleAttributeRow[]): SampleAttributeRow[] => rows.filter((row) => row.key === 'service.name')
const lineCount = (rows: SampleAttributeRow[]): number => lines(rows).reduce((sum, row) => sum + row.count, 0)
const byCount = (row: SampleAttributeRow): number => row.count

function attributeKeys(sql: string): Counted {
    const rows = scoped(sql).filter((row) => !sql.includes("attribute_type != 'span'") || row.key !== 'name')
    const onLines = new Set(rows.filter((row) => !row.isResource).map((row) => row.key))
    return tally(rows, (row) => row.key, byCount).filter(
        ([key]) => !sql.includes('HAVING min(attribute_type') || !onLines.has(key)
    )
}

function attributeValues(sql: string): Counted {
    const key = attributeKey(sql)
    return tally(
        scoped(sql).filter((row) => row.key === key),
        (row) => row.value,
        byCount
    )
}

function facetRows(sql: string): Rows {
    return sql.split('UNION ALL').flatMap((part) => {
        const facet = new RegExp(`SELECT '(${TEXT})' AS facet`).exec(part)
        if (!facet) {
            return []
        }
        const key = unescape(facet[1])
        const column = key === 'severity_text' ? 'level' : key === 'service_name' ? 'service' : 'value'
        const rows = column === 'value' ? scoped(part).filter((row) => row.key === key) : lines(scoped(part))
        const resource = rows.every((row) => row.isResource) ? 1 : 0
        return tally(rows, (row) => row[column], byCount)
            .slice(0, 10)
            .map(([value, count]) => [key, value, count, resource])
    })
}

function logKeyRows(sql: string): Rows {
    const rows = scoped(sql)
    const total = lineCount(rows)
    const onLines = new Set(rows.filter((row) => !row.isResource).map((row) => row.key))
    return tally(rows, (row) => row.key, byCount).map(([key, count]) => [key, count, onLines.has(key) ? 0 : 1, total])
}

function logValueRows(sql: string): Rows {
    const rows = scoped(sql)
    const total = lineCount(rows)
    const search = searchOf(sql)
    const values = sql.includes('SELECT severity_text AS prop_value')
        ? tally(lines(rows), (row) => row.level, byCount)
        : attributeValues(sql)
    return values
        .filter(([value]) => has(value, search))
        .slice(0, 50)
        .map(([value, count]) => [value, count, total])
}

const COMPARISON = new RegExp(
    `(?:coalesce\\(nullIf\\(attributes\\['(${TEXT})'\\], ''\\), resource_attributes\\['${TEXT}'\\]\\)|resource_attributes\\['(${TEXT})'\\]) (=|!=) '(${TEXT})'`,
    'g'
)

function durationRows(sql: string): Rows {
    const edges = [0, ...[...sql.matchAll(/duration_nano \/ 1e6 < (\d+), \d+/g)].map((match) => Number(match[1]))]
    const services = new Set(scoped(sql, SAMPLE_TRACE_ATTRIBUTES).map((row) => row.service))
    const names = listOf(sql, 'name')
    const comparisons = [...sql.matchAll(COMPARISON)].map(([, attribute, resource, operator, value]) => ({
        key: unescape(attribute ?? resource),
        value: unescape(value),
        excluded: operator === '!=',
    }))
    const counts = edges.map(() => 0)
    for (const span of SAMPLE_SPANS) {
        const attributes = { ...spanResourceAttributes(span.service), ...span.attributes }
        if (
            !services.has(span.service) ||
            (names && !names.includes(span.name)) ||
            (sql.includes('is_root_span') && !span.root) ||
            comparisons.some(({ key, value, excluded }) => (attributes[key] === value) === excluded)
        ) {
            continue
        }
        const kept = sql.includes('status_code = 2')
            ? span.errorRate
            : sql.includes('status_code != 2')
              ? 1 - span.errorRate
              : 1
        const weights = edges.map((low, bucket) => {
            const middle = Math.sqrt(Math.max(low, 1) * (edges[bucket + 1] ?? low * 4))
            return Math.exp(-(Math.log(middle / span.medianMs) ** 2) / 1.6)
        })
        const weight = weights.reduce((sum, value) => sum + value, 0)
        weights.forEach((value, bucket) => (counts[bucket] += (span.count * kept * value) / weight))
    }
    return counts.map((count, bucket) => [bucket, Math.round(count)]).filter(([, count]) => count > 0)
}

type PropertyKind = 'event' | 'person'

const EVENT_VALUE = `JSONExtractRaw\\(properties, '(${TEXT})'\\), '\\^"\\|"\\$', ''\\)`
const PERSON_VALUE = `toString\\(person\\.properties\\['(${TEXT})'\\]\\)`
const NARROWED = new RegExp(`(?:${EVENT_VALUE}|${PERSON_VALUE}) = '(${TEXT})'`, 'g')
const VALUE_OF = new RegExp(`(?:${EVENT_VALUE}|${PERSON_VALUE})\\)? AS [vx]\\b`)

const propertiesOf = (kind: PropertyKind): SampleProperty[] =>
    kind === 'person' ? SAMPLE_PERSON_PROPERTIES : SAMPLE_EVENT_PROPERTIES
const volume = (events: SampleEvent[]): number => events.reduce((sum, event) => sum + event.count, 0)

function coverage(property: SampleProperty, events: SampleEvent[]): number {
    const carrying = events.filter((event) => !property.events || property.events.includes(event.name))
    return property.share * (volume(carrying) / volume(events))
}

function sampleOf(
    sql: string,
    kind: PropertyKind
): { events: SampleEvent[]; total: number; narrowed: Map<string, string> } {
    const names = listOf(sql, 'event')
    const picked = SAMPLE_EVENTS.filter((event) => names?.includes(event.name))
    const events = picked.length ? picked : SAMPLE_EVENTS
    const narrowed = new Map<string, string>()
    let total = Math.min(kind === 'person' ? 5000 : 20_000, volume(events) / 7)
    for (const [, eventKey, personKey, rawValue] of sql.matchAll(NARROWED)) {
        const narrowedKind = eventKey === undefined ? 'person' : 'event'
        const key = unescape(eventKey ?? personKey)
        const value = unescape(rawValue)
        if (narrowed.has(`${narrowedKind}:${key}`)) {
            continue
        }
        narrowed.set(`${narrowedKind}:${key}`, value)
        const property = propertiesOf(narrowedKind).find((candidate) => candidate.key === key)
        const portion = property && portions(property.values).find(([candidate]) => candidate === value)?.[1]
        total *= property && portion ? coverage(property, events) * portion : 0.1
    }
    return { events, total: Math.round(total), narrowed }
}

function propertyKeyRows(sql: string, kind: PropertyKind): Rows {
    const { events, total, narrowed } = sampleOf(sql, kind)
    return propertiesOf(kind)
        .filter((property) => !property.unseen)
        .map((property): [string, number, number] => [
            property.key,
            Math.round(total * (narrowed.has(`${kind}:${property.key}`) ? 1 : coverage(property, events))),
            total,
        ])
        .filter(([, count]) => count > 0)
        .sort((a, b) => b[1] - a[1])
}

function propertyOf(sql: string): { kind: PropertyKind; property?: SampleProperty } {
    const match = VALUE_OF.exec(sql)
    const kind = match?.[1] === undefined ? 'person' : 'event'
    const key = unescape(match?.[1] ?? match?.[2] ?? '')
    return { kind, property: propertiesOf(kind).find((candidate) => candidate.key === key) }
}

function propertyValueRows(sql: string): Rows {
    const { kind, property } = propertyOf(sql)
    if (!property) {
        return []
    }
    const { events, total, narrowed } = sampleOf(sql, kind)
    const only = narrowed.get(`${kind}:${property.key}`)
    const search = searchOf(sql)
    const having = total * (only === undefined ? coverage(property, events) : 1)
    return portions(property.values)
        .filter(([value]) => (only === undefined || value === only) && has(value, search))
        .map(([value, portion]): [string, number, number] => [
            value,
            Math.round(having * (only === undefined ? portion : 1)),
            total,
        ])
        .filter(([, count]) => count > 0)
        .sort((a, b) => b[1] - a[1])
}

function propertyStatsRows(sql: string): Rows {
    const { kind, property } = propertyOf(sql)
    const numbers = portions(property?.values ?? [])
        .map(([value, portion]) => ({ value: Number(value), portion }))
        .filter(({ value }) => Number.isFinite(value))
        .sort((a, b) => a.value - b.value)
    if (!property || !numbers.length) {
        return []
    }
    const { events, total } = sampleOf(sql, kind)
    let below = 0
    const median = numbers.find(({ portion }) => (below += portion) >= 0.5) ?? numbers[numbers.length - 1]
    const mean = numbers.reduce((sum, { value, portion }) => sum + value * portion, 0)
    const count = Math.round(total * coverage(property, events))
    return [[numbers[0].value, median.value, numbers[numbers.length - 1].value, mean, count]]
}

function propertyDefinitionRows(sql: string): Rows {
    const names = listOf(sql, 'name')
    const search = searchOf(sql)
    return propertiesOf(sql.includes("type = 'person'") ? 'person' : 'event')
        .filter(
            (property) =>
                (!names || names.includes(property.key)) &&
                (!sql.includes('NOT startsWith(name') || !property.key.startsWith('$feature')) &&
                has(property.key, search)
        )
        .map((property) => [property.key, property.type])
}

function eventPropertyValues(sql: string): Counted {
    const key = new RegExp(`JSONExtractString\\(properties, '(${TEXT})'\\)`).exec(sql)
    return SAMPLE_EVENT_PROPERTIES.find((property) => key && property.key === unescape(key[1]))?.values ?? []
}

const TABLES: { marker: string; columns: string[]; rows: (sql: string) => Rows }[] = [
    { marker: 'SELECT facet, value, n, resource FROM', columns: ['facet', 'value', 'n', 'resource'], rows: facetRows },
    { marker: 'AS bucket, count() AS n', columns: ['bucket', 'n'], rows: durationRows },
    {
        marker: 'FROM system.property_definitions',
        columns: ['prop_key', 'prop_type'],
        rows: propertyDefinitionRows,
    },
    {
        marker: 'FROM system.cohorts',
        columns: ['cohort_id', 'name', 'count', 'is_static'],
        rows: () => SAMPLE_COHORTS.map((cohort) => [cohort.id, cohort.name, cohort.count, cohort.isStatic ? 1 : 0]),
    },
    {
        marker: 'FROM system.actions',
        columns: ['action_id', 'name', 'description'],
        rows: () => SAMPLE_ACTIONS.map((action) => [action.id, action.name, action.description]),
    },
    {
        marker: 'SELECT k AS prop_key',
        columns: ['prop_key', 'n', 'total'],
        rows: (sql) => propertyKeyRows(sql, sql.includes('person.properties AS p') ? 'person' : 'event'),
    },
    { marker: 'SELECT v AS prop_value', columns: ['prop_value', 'n', 'total'], rows: propertyValueRows },
    {
        marker: 'SELECT min(x) AS prop_min',
        columns: ['prop_min', 'median', 'max', 'mean', 'n'],
        rows: propertyStatsRows,
    },
    {
        marker: 'SELECT event AS entity',
        columns: ['entity', 'n'],
        rows: () => SAMPLE_EVENTS.map((event) => [event.name, event.count]),
    },
    {
        marker: 'SELECT service_name AS entity',
        columns: ['entity', 'n'],
        rows: (sql) => tally(lines(scoped(sql)), (row) => row.service, byCount),
    },
    {
        marker: 'SELECT attribute_key AS prop_key',
        columns: ['prop_key', 'n', 'resource', 'total'],
        rows: logKeyRows,
    },
    { marker: 'SELECT severity_text AS prop_value', columns: ['prop_value', 'n', 'total'], rows: logValueRows },
    { marker: 'SELECT attribute_value AS prop_value', columns: ['prop_value', 'n', 'total'], rows: logValueRows },
]

const OPTIONS: { marker: string; counted?: boolean; options: (sql: string) => Counted }[] = [
    {
        marker: 'SELECT event, count() AS n FROM events',
        counted: true,
        options: () => SAMPLE_EVENTS.map((event) => [event.name, event.count]),
    },
    {
        marker: 'SELECT k FROM (SELECT properties FROM events',
        options: (sql) => propertyKeyRows(sql, 'event').map(([key, count]) => [String(key), Number(count)]),
    },
    { marker: 'SELECT JSONExtractString(properties,', options: eventPropertyValues },
    {
        marker: 'SELECT service_name FROM',
        options: (sql) => tally(lines(scoped(sql)), (row) => row.service, byCount),
    },
    {
        marker: 'SELECT severity_text FROM logs',
        options: (sql) => tally(lines(scoped(sql)), (row) => row.level, byCount),
    },
    { marker: 'SELECT attribute_key AS k FROM', options: attributeKeys },
    { marker: 'SELECT attribute_value AS v FROM', options: attributeValues },
]

function sampleOptions(
    language: string | undefined,
    query: string,
    search = ''
): { options: string[]; total: number; details?: Record<string, string> } {
    const source = language === 'promql' ? undefined : OPTIONS.find(({ marker }) => query.includes(marker))
    const all: Counted =
        language === 'promql' ? metricOptions(query).map((option) => [option, 0]) : (source?.options(query) ?? [])
    const typed = (search.trim() || searchOf(query)).toLowerCase()
    const found = all.filter(([option]) => has(option, typed))
    return {
        options: found.map(([option]) => option),
        total: found.length,
        ...(source?.counted && {
            details: Object.fromEntries(found.map(([option, count]) => [option, String(count)])),
        }),
    }
}
