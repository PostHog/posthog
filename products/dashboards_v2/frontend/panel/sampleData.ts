import type { FlameNode } from '@posthog/quill-charts'

import type { MetricsChartSeries } from 'products/metrics/frontend/components/metricsSeries'
import type { TrendsResultLike } from 'products/product_analytics/frontend/insights/trends/TrendsLineChart/trendsChartTransforms'

import type { DataFrame } from '../charts/frame'
import type { PanelCategory, PanelData } from '../charts/panelData'
import type { DashboardV2PanelApi } from '../generated/api.schemas'

interface TimeRange {
    from: number
    to: number
}

const STEPS_MS = [60_000, 300_000, 900_000, 3_600_000, 21_600_000, 86_400_000, 604_800_000]
const CATEGORIES = ['Chrome', 'Safari', 'Firefox', 'Edge', 'Other']
const FUNNEL_STEPS = ['Visited', 'Signed up', 'Created project', 'Sent first event', 'Invited a teammate']
const SERVICES = ['web', 'api', 'ingestion', 'billing', 'worker']
const HISTOGRAM_BOUNDS = [0.1, 0.5, 1, 2.5, 5, 10]
const MAX_SERIES = 4
const LOG_LINES: [string, string][] = [
    ['info', 'GET /api/projects 200 in 42 ms'],
    ['info', 'Flushed 128 events to the queue'],
    ['debug', 'Cache hit for feature flags'],
    ['warn', 'Retrying request to the payment provider (attempt 2)'],
    ['error', 'Timed out after 30 s waiting for the database'],
    ['info', 'Session started for a new visitor'],
    ['warn', 'Slow query: 2.4 s on events table'],
    ['error', 'Unhandled exception in the export job'],
]

function seededRandom(seed: string): () => number {
    let state = 0
    for (let index = 0; index < seed.length; index++) {
        state = (Math.imul(state, 31) + seed.charCodeAt(index)) | 0
    }
    return () => {
        state = (state + 0x6d2b79f5) | 0
        let mixed = Math.imul(state ^ (state >>> 15), 1 | state)
        mixed = (mixed + Math.imul(mixed ^ (mixed >>> 7), 61 | mixed)) ^ mixed
        return ((mixed ^ (mixed >>> 14)) >>> 0) / 4294967296
    }
}

function scaleFor(unit: string | null | undefined): number {
    if (unit === 'percentunit' || unit === '1') {
        return 1
    }
    return unit === 'percent' || unit === '%' ? 100 : 1000
}

function rounded(value: number, scale: number): number {
    const factor = scale >= 1000 ? 1 : scale >= 100 ? 10 : 1000
    return Math.round(value * factor) / factor
}

function timesIn(range: TimeRange): number[] {
    const span = range.to - range.from
    const step = STEPS_MS.find((candidate) => span / candidate <= 60) ?? STEPS_MS[STEPS_MS.length - 1]
    const times: number[] = []
    for (let time = Math.ceil(range.from / step) * step; time <= range.to; time += step) {
        times.push(time)
    }
    return times
}

function wave(times: number[], random: () => number, scale: number, divisor: number): number[] {
    const base = (scale * (0.3 + 0.5 * random())) / divisor
    const phase = random() * Math.PI * 2
    return times.map((_, index) =>
        rounded(base * (1 + 0.25 * Math.sin(index / 6 + phase) + 0.15 * (random() - 0.5)), scale)
    )
}

function seriesNames(panel: DashboardV2PanelApi): string[] {
    const targets = (panel.targets ?? []).filter((target) => !target.hide)
    if (targets.length <= 1) {
        return [panel.title || 'Value']
    }
    return targets.slice(0, MAX_SERIES).map((target) => target.refId)
}

function metricSeries(names: string[], range: TimeRange, random: () => number, scale: number): MetricsChartSeries[] {
    const times = timesIn(range)
    return names.map((name, index) => ({
        labels: {},
        metricName: names.length > 1 ? name : undefined,
        points: wave(times, random, scale, index + 1).map((value, point) => ({
            time: new Date(times[point]).toISOString(),
            value,
        })),
    }))
}

function trendsResults(names: string[], range: TimeRange, random: () => number, scale: number): TrendsResultLike[] {
    const times = timesIn(range)
    const days = times.map((time) => new Date(time).toISOString())
    return names.map((name, index) => ({ id: index, label: name, data: wave(times, random, scale, index + 1), days }))
}

function categories(labels: string[], random: () => number, scale: number): PanelCategory[] {
    return labels.map((label, index) => ({
        label,
        value: rounded((scale * (0.4 + 0.6 * random())) / (index + 1), scale),
    }))
}

function funnelSteps(random: () => number): PanelCategory[] {
    let value = 1000
    return FUNNEL_STEPS.map((label, index) => {
        if (index > 0) {
            value = Math.round(value * (0.55 + 0.35 * random()))
        }
        return { label, value }
    })
}

function histogram(range: TimeRange, random: () => number): PanelData {
    const times = timesIn(range)
    return {
        kind: 'histogram',
        histogram: {
            results: null,
            times: times.map((time) => new Date(time).toISOString()),
            bounds: HISTOGRAM_BOUNDS,
            counts: HISTOGRAM_BOUNDS.map((_, bucket) =>
                times.map((__, index) => {
                    const peak = 1.5 + 1.5 * Math.sin(index / 5)
                    return Math.round(400 * Math.exp(-((bucket - peak) ** 2) / 1.5) * (0.6 + 0.8 * random()))
                })
            ),
        },
    }
}

function flows(random: () => number): PanelData {
    const links: [string, string][] = [
        ['Home', 'Pricing'],
        ['Home', 'Docs'],
        ['Home', 'Sign up'],
        ['Pricing', 'Sign up'],
        ['Docs', 'Sign up'],
        ['Sign up', 'Onboarding'],
        ['Onboarding', 'First event'],
    ]
    return {
        kind: 'flows',
        flows: links.map(([source, target]) => ({ source, target, value: Math.round(100 + 400 * random()) })),
    }
}

function boxes(range: TimeRange, random: () => number): PanelData {
    const days = 7
    const step = (range.to - range.from) / days
    const medians = Array.from({ length: days }, () => 200 + 200 * random())
    return {
        kind: 'boxes',
        labels: medians.map((_, index) => new Date(Math.round(range.from + index * step)).toISOString()),
        boxes: medians.map((median, index) => ({
            day: new Date(Math.round(range.from + index * step)).toISOString(),
            min: Math.round(median * 0.3),
            p25: Math.round(median * 0.7),
            median: Math.round(median),
            mean: Math.round(median * 1.05),
            p75: Math.round(median * 1.4),
            max: Math.round(median * 2.2),
        })),
    }
}

function flame(random: () => number): PanelData {
    const leaf = (name: string): FlameNode => ({ name, value: Math.round(20 + 200 * random()) })
    const parent = (name: string, children: FlameNode[]): FlameNode => ({
        name,
        value: children.reduce((sum, child) => sum + child.value, 0),
        children,
    })
    return {
        kind: 'flame',
        roots: [
            parent('request', [
                parent('auth', [leaf('session'), leaf('token')]),
                parent('query', [leaf('parse'), parent('execute', [leaf('scan'), leaf('sort')])]),
                leaf('render'),
            ]),
        ],
    }
}

function hexId(random: () => number, length: number): string {
    let id = ''
    while (id.length < length) {
        id += Math.floor(random() * 16).toString(16)
    }
    return id
}

function volumeFrames(names: string[], range: TimeRange, random: () => number): DataFrame[] {
    const times = timesIn(range)
    return names.map((name, index) => ({
        name,
        fields: [
            { name: 'time', type: 'time', values: times },
            { name: 'value', type: 'number', values: wave(times, random, 100, index + 1) },
        ],
    }))
}

function logFrames(range: TimeRange, random: () => number): DataFrame[] {
    const count = 80
    const rows = Array.from({ length: count }, (_, index) => {
        const [level, body] = LOG_LINES[Math.floor(random() * LOG_LINES.length)]
        const service = SERVICES[Math.floor(random() * SERVICES.length)]
        return {
            time: Math.round(range.to - ((range.to - range.from) * index) / count),
            level,
            service,
            body,
            attributes: {
                'http.method': 'GET',
                region: random() > 0.5 ? 'us-east-1' : 'eu-central-1',
                pod: `${service}-${hexId(random, 5)}`,
            },
            resource: { 'service.name': service, 'deployment.environment': 'production' },
            trace: hexId(random, 32),
        }
    })
    return [
        {
            fields: [
                { name: 'timestamp', type: 'time', values: rows.map((row) => row.time) },
                { name: 'level', type: 'string', values: rows.map((row) => row.level) },
                { name: 'service', type: 'string', values: rows.map((row) => row.service) },
                { name: 'body', type: 'string', values: rows.map((row) => row.body) },
                { name: 'attributes', type: 'other', values: rows.map((row) => row.attributes) },
                { name: 'resource_attributes', type: 'other', values: rows.map((row) => row.resource) },
                { name: 'trace_id', type: 'string', values: rows.map((row) => row.trace) },
            ],
        },
        ...volumeFrames(['info', 'warn', 'error'], range, random),
    ]
}

function traceFrames(range: TimeRange, random: () => number): DataFrame[] {
    const operations = ['GET /checkout', 'POST /api/orders', 'GET /api/projects', 'POST /capture']
    const steps = ['auth.verify', 'db.query', 'cache.get', 'queue.publish']
    const spans: Record<string, unknown>[] = []
    for (let trace = 0; trace < 24; trace++) {
        const traceId = hexId(random, 32)
        const rootId = hexId(random, 16)
        const start = Math.round(range.from + (range.to - range.from) * random())
        const duration = Math.round(40 + 900 * random() * random())
        const failed = random() > 0.85
        spans.push({
            span_id: rootId,
            trace_id: traceId,
            parent_span_id: '',
            name: operations[trace % operations.length],
            service: 'web',
            timestamp: start,
            duration_ms: duration,
            status_code: failed ? 2 : 1,
            attributes: { 'http.status_code': failed ? 500 : 200 },
        })
        let offset = 2
        steps.slice(0, 2 + Math.floor(random() * 3)).forEach((name, index) => {
            const length = Math.round((duration / 5) * (0.4 + random()))
            spans.push({
                span_id: hexId(random, 16),
                trace_id: traceId,
                parent_span_id: rootId,
                name,
                service: SERVICES[1 + (index % (SERVICES.length - 1))],
                timestamp: start + offset,
                duration_ms: length,
                status_code: failed && index === 0 ? 2 : 1,
                attributes: { 'db.system': 'postgresql' },
            })
            offset += length
        })
    }
    const column = (name: string, type: 'string' | 'number' | 'time' | 'other'): DataFrame['fields'][number] => ({
        name,
        type,
        values: spans.map((span) => span[name]),
    })
    return [
        {
            fields: [
                column('span_id', 'string'),
                column('trace_id', 'string'),
                column('parent_span_id', 'string'),
                column('name', 'string'),
                column('service', 'string'),
                column('timestamp', 'time'),
                column('duration_ms', 'number'),
                column('status_code', 'number'),
                column('attributes', 'other'),
            ],
        },
        ...volumeFrames(['ok', 'error'], range, random),
    ]
}

export function sampleData(id: string, panel: DashboardV2PanelApi, range: TimeRange): PanelData | null {
    const random = seededRandom(`${id}:${panel.viz.type}`)
    const scale = scaleFor(panel.fieldConfig?.unit)
    const fromEvents = (panel.targets ?? []).find((target) => !target.hide)?.language === 'insight'
    switch (panel.viz.type) {
        case 'timeseries':
            return fromEvents && panel.viz.options?.style !== 'bars'
                ? { kind: 'trends', results: trendsResults(seriesNames(panel), range, random, scale) }
                : { kind: 'series', series: metricSeries(seriesNames(panel), range, random, scale) }
        case 'stat':
        case 'gauge':
            return { kind: 'series', series: metricSeries([panel.title || 'Value'], range, random, scale) }
        case 'table':
            return { kind: 'series', series: metricSeries(CATEGORIES, range, random, scale) }
        case 'heatmap':
            return histogram(range, random)
        case 'bar':
            return panel.viz.options?.funnel
                ? { kind: 'categories', categories: funnelSteps(random) }
                : { kind: 'categories', categories: categories(CATEGORIES, random, scale) }
        case 'pie':
            return { kind: 'categories', categories: categories(CATEGORIES, random, scale) }
        case 'sankey':
            return flows(random)
        case 'boxplot':
            return boxes(range, random)
        case 'flamegraph':
            return flame(random)
        case 'logs':
            return { kind: 'frames', frames: logFrames(range, random) }
        case 'traces':
            return { kind: 'frames', frames: traceFrames(range, random) }
        default:
            return null
    }
}
