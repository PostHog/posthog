import type { DataFrame } from '../charts/frame'
import type { DashboardV2PanelApi } from '../generated/api.schemas'

const STEPS_MS = [60_000, 300_000, 900_000, 3_600_000, 21_600_000, 86_400_000, 604_800_000]
const CATEGORIES = ['Chrome', 'Safari', 'Firefox', 'Edge', 'Other']
const MAX_SERIES = 4

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
    if (unit === 'percentunit') {
        return 1
    }
    return unit === 'percent' ? 100 : 1000
}

function rounded(value: number, scale: number): number {
    const factor = scale >= 1000 ? 1 : scale >= 100 ? 10 : 1000
    return Math.round(value * factor) / factor
}

function seriesNames(panel: DashboardV2PanelApi): string[] {
    const targets = (panel.targets ?? []).filter((target) => !target.hide)
    if (targets.length <= 1) {
        return [panel.title || 'Value']
    }
    return targets.slice(0, MAX_SERIES).map((target) => target.refId)
}

function timeSeriesFrames(
    names: string[],
    range: { from: number; to: number },
    random: () => number,
    scale: number
): DataFrame[] {
    const span = range.to - range.from
    const step = STEPS_MS.find((candidate) => span / candidate <= 60) ?? STEPS_MS[STEPS_MS.length - 1]
    const times: number[] = []
    for (let time = Math.ceil(range.from / step) * step; time <= range.to; time += step) {
        times.push(time)
    }
    return names.map((name, seriesIndex) => {
        const base = (scale * (0.3 + 0.5 * random())) / (seriesIndex + 1)
        const phase = random() * Math.PI * 2
        return {
            name,
            fields: [
                { name: 'time', type: 'time', values: times },
                {
                    name: 'value',
                    type: 'number',
                    values: times.map((_, index) =>
                        rounded(base * (1 + 0.25 * Math.sin(index / 6 + phase) + 0.15 * (random() - 0.5)), scale)
                    ),
                },
            ],
        }
    })
}

function categoryFrames(random: () => number, scale: number): DataFrame[] {
    return [
        {
            fields: [
                { name: 'name', type: 'string', values: CATEGORIES },
                {
                    name: 'value',
                    type: 'number',
                    values: CATEGORIES.map((_, index) =>
                        rounded((scale * (0.4 + 0.6 * random())) / (index + 1), scale)
                    ),
                },
            ],
        },
    ]
}

function tableFrames(random: () => number): DataFrame[] {
    const counts = CATEGORIES.map((_, index) => Math.round((1000 * (0.4 + 0.6 * random())) / (index + 1)))
    const total = counts.reduce((sum, count) => sum + count, 0)
    return [
        {
            fields: [
                { name: 'name', type: 'string', values: CATEGORIES },
                { name: 'count', type: 'number', values: counts },
                {
                    name: 'share',
                    type: 'number',
                    values: counts.map((count) => Math.round((1000 * count) / total) / 10),
                    config: { unit: 'percent' },
                },
            ],
        },
    ]
}

function heatmapFrames(range: { from: number; to: number }, random: () => number): DataFrame[] {
    return timeSeriesFrames(['0.1', '0.5', '1', '2.5', '5', '10'], range, random, 1000).map((frame, bucket) => ({
        ...frame,
        fields: frame.fields.map((field) =>
            field.type === 'number'
                ? {
                      ...field,
                      values: field.values.map((_, index) => {
                          const peak = 1.5 + 1.5 * Math.sin(index / 5)
                          return Math.round(400 * Math.exp(-((bucket - peak) ** 2) / 1.5) * (0.6 + 0.8 * random()))
                      }),
                  }
                : field
        ),
    }))
}

function retentionFrames(random: () => number): DataFrame[] {
    const weeks = 6
    const sizes = Array.from({ length: weeks }, () => Math.round(400 + 400 * random()))
    return [
        {
            fields: [
                { name: 'cohort', type: 'string', values: sizes.map((_, index) => `Week ${index + 1}`) },
                { name: 'size', type: 'number', values: sizes },
                ...Array.from({ length: weeks }, (_, period) => ({
                    name: `Week ${period}`,
                    type: 'number' as const,
                    values: sizes.map((size, cohort) =>
                        period > weeks - 1 - cohort
                            ? null
                            : Math.round(size * (period === 0 ? 1 : (0.55 + 0.1 * random()) / Math.sqrt(period)))
                    ),
                })),
            ],
        },
    ]
}

function flowFrames(random: () => number): DataFrame[] {
    const links: [string, string][] = [
        ['Home', 'Pricing'],
        ['Home', 'Docs'],
        ['Home', 'Sign up'],
        ['Pricing', 'Sign up'],
        ['Docs', 'Sign up'],
        ['Sign up', 'Onboarding'],
        ['Onboarding', 'First event'],
    ]
    return [
        {
            fields: [
                { name: 'source', type: 'string', values: links.map(([source]) => source) },
                { name: 'target', type: 'string', values: links.map(([, target]) => target) },
                { name: 'value', type: 'number', values: links.map(() => Math.round(100 + 400 * random())) },
            ],
        },
    ]
}

function boxFrames(range: { from: number; to: number }, random: () => number): DataFrame[] {
    const days = 7
    const step = (range.to - range.from) / days
    const medians = Array.from({ length: days }, () => 200 + 200 * random())
    const column = (name: string, factor: number): DataFrame['fields'][number] => ({
        name,
        type: 'number',
        values: medians.map((median) => Math.round(median * factor)),
    })
    return [
        {
            fields: [
                {
                    name: 'time',
                    type: 'time',
                    values: medians.map((_, index) => Math.round(range.from + index * step)),
                },
                column('min', 0.3),
                column('p25', 0.7),
                column('median', 1),
                column('p75', 1.4),
                column('max', 2.2),
            ],
        },
    ]
}

function flameFrames(random: () => number): DataFrame[] {
    const stacks = [
        'request;auth;session',
        'request;auth;token',
        'request;query;parse',
        'request;query;execute;scan',
        'request;query;execute;sort',
        'request;render',
    ]
    return [
        {
            fields: [
                { name: 'stack', type: 'string', values: stacks },
                { name: 'value', type: 'number', values: stacks.map(() => Math.round(20 + 200 * random())) },
            ],
        },
    ]
}

const SERVICES = ['web', 'api', 'ingestion', 'billing', 'worker']
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

function hexId(random: () => number, length: number): string {
    let id = ''
    while (id.length < length) {
        id += Math.floor(random() * 16).toString(16)
    }
    return id
}

function volumeFrames(names: string[], range: { from: number; to: number }, random: () => number): DataFrame[] {
    return timeSeriesFrames(names, range, random, 100)
}

function logFrames(range: { from: number; to: number }, random: () => number): DataFrame[] {
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

function traceFrames(range: { from: number; to: number }, random: () => number): DataFrame[] {
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

export function sampleFrames(id: string, panel: DashboardV2PanelApi, range: { from: number; to: number }): DataFrame[] {
    const random = seededRandom(`${id}:${panel.viz.type}`)
    const scale = scaleFor(panel.fieldConfig?.unit)
    switch (panel.viz.type) {
        case 'timeseries':
            return timeSeriesFrames(seriesNames(panel), range, random, scale)
        case 'stat':
        case 'gauge':
            return timeSeriesFrames([panel.title || 'Value'], range, random, scale)
        case 'heatmap':
            return heatmapFrames(range, random)
        case 'retention':
            return retentionFrames(random)
        case 'sankey':
            return flowFrames(random)
        case 'boxplot':
            return boxFrames(range, random)
        case 'flamegraph':
            return flameFrames(random)
        case 'logs':
            return logFrames(range, random)
        case 'traces':
            return traceFrames(range, random)
        case 'bar':
        case 'pie':
            return categoryFrames(random, scale)
        case 'table':
            return tableFrames(random)
        default:
            return []
    }
}
