// Pure helpers shared by the insight terminal renderer — no I/O so they can
// be unit-tested.

export type JsonRecord = Record<string, unknown>

export type ChartSeries = JsonRecord & { data: unknown[]; labels: unknown[] }

/**
 * MCP tool names whose responses we render as an insight (chart, funnel table,
 * etc.) instead of a generic object summary. Both the renderer dispatch in
 * `output.ts` and the `refresh=blocking` injection in `index.ts` key off this
 * set, so a tool rename only needs one update.
 */
export const CHARTABLE_INSIGHT_TOOLS: ReadonlySet<string> = new Set(['insight-get'])

export const Y_AXIS_PAD = 7
const MAX_STEP = 20

export function isRecord(value: unknown): value is JsonRecord {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function stringify(value: unknown): string {
    if (value === null || value === undefined) {
        return ''
    }
    if (typeof value === 'string') {
        return value.replace(/[\u0000-\u001F\u007F-\u009F]/g, '')
    }
    return String(value)
}

export function isChartSeries(value: unknown): value is ChartSeries {
    return (
        isRecord(value) &&
        Array.isArray(value.data) &&
        Array.isArray(value.labels) &&
        value.data.length > 0 &&
        value.labels.length > 0
    )
}

export function getInsightType(insight: JsonRecord): string {
    const query = insight.query
    if (isRecord(query) && typeof query.kind === 'string') {
        if (query.kind === 'InsightVizNode' && isRecord(query.source) && typeof query.source.kind === 'string') {
            return query.source.kind
        }
        return query.kind
    }
    return 'Insight'
}

export function widenSeries(series: number[], step: number): number[] {
    if (step <= 1 || series.length === 0) {
        return series.slice()
    }
    const out: number[] = []
    for (let i = 0; i < series.length - 1; i++) {
        const a = series[i]
        const b = series[i + 1]
        for (let k = 0; k < step; k++) {
            out.push(a + ((b - a) * k) / step)
        }
    }
    out.push(series[series.length - 1])
    return out
}

export function formatYValue(x: number): string {
    if (!Number.isFinite(x)) {
        return '0'
    }
    const abs = Math.abs(x)
    // Bucket boundaries are picked so that toFixed-rounding cannot push the
    // result into the next magnitude — e.g. -9999 would round to "-10.0k" (6
    // chars), overflowing the 5-char Y-axis width budget. Promoting to the
    // wider bucket early keeps every output within budget.
    if (abs >= 9_500_000_000) {
        return `${(x / 1_000_000_000).toFixed(0)}B`
    }
    if (abs >= 999_500_000) {
        return `${(x / 1_000_000_000).toFixed(1)}B`
    }
    if (abs >= 9_500_000) {
        return `${(x / 1_000_000).toFixed(0)}M`
    }
    if (abs >= 999_500) {
        return `${(x / 1_000_000).toFixed(1)}M`
    }
    if (abs >= 9_950) {
        return `${(x / 1_000).toFixed(0)}k`
    }
    if (abs >= 1_000) {
        return `${(x / 1_000).toFixed(1)}k`
    }
    return x.toFixed(0)
}

export function pickStep(points: number, termWidth: number): number {
    const widthBudget = termWidth - Y_AXIS_PAD - 2
    let step = Math.floor(widthBudget / Math.max(1, points - 1))
    if (step < 1) step = 1
    if (step > MAX_STEP) step = MAX_STEP
    return step
}

// Maximum data points that fit on a single chart row at step=1.
// Used as the bucket target when downsampling oversized series.
export function maxRenderablePoints(termWidth: number): number {
    return Math.max(2, termWidth - Y_AXIS_PAD - 2)
}

// Bucketed-mean downsample. When a time series has more points than the chart
// can render at step=1 the chart overflows the terminal — bucketing keeps the
// visual shape while making it fit. Identity when `values.length <= maxPoints`.
export function bucketAverage(values: number[], maxPoints: number): number[] {
    if (maxPoints <= 0 || values.length <= maxPoints) {
        return values.slice()
    }
    const bucketSize = Math.ceil(values.length / maxPoints)
    const out: number[] = []
    for (let i = 0; i < values.length; i += bucketSize) {
        let sum = 0
        let count = 0
        for (let k = i; k < Math.min(i + bucketSize, values.length); k++) {
            sum += values[k]
            count++
        }
        out.push(count > 0 ? sum / count : 0)
    }
    return out
}

// Stride sampling for label arrays (strings can't be averaged). Takes the first
// label of each bucket so the resulting positions line up with `bucketAverage`.
export function bucketLabels<T>(labels: T[], maxPoints: number): T[] {
    if (maxPoints <= 0 || labels.length <= maxPoints) {
        return labels.slice()
    }
    const bucketSize = Math.ceil(labels.length / maxPoints)
    const out: T[] = []
    for (let i = 0; i < labels.length; i += bucketSize) {
        out.push(labels[i])
    }
    return out
}

// PostHog's data palette (frontend/src/styles/base.scss data-color-1..15).
// Kept in sync with the web app so terminal charts pick the same series colors.
export const POSTHOG_COLORS: readonly string[] = [
    '#1d4aff', // data-color-1
    '#621da6', // data-color-2
    '#42827e', // data-color-3
    '#ce7c00', // data-color-4
    '#de4916', // data-color-5
    '#8b0014', // data-color-6
    '#b64b94', // data-color-7
    '#487968', // data-color-8
    '#8b4513', // data-color-9
    '#4682b4', // data-color-10
    '#191970', // data-color-11
    '#008b8b', // data-color-12
    '#b8860b', // data-color-13
    '#ff6347', // data-color-14
    '#30d5c8', // data-color-15
]

export function parseHex(hex: string): { r: number; g: number; b: number } {
    const value = hex.startsWith('#') ? hex.slice(1) : hex
    return {
        r: parseInt(value.slice(0, 2), 16),
        g: parseInt(value.slice(2, 4), 16),
        b: parseInt(value.slice(4, 6), 16),
    }
}

// 24-bit truecolor SGR. Every modern terminal renders this; asciichart just
// concats the escape with the glyph + reset, so a unique hex stays distinct
// instead of collapsing onto one of the eight named ANSI colors.
export function hexToAnsi(hex: string): string {
    const { r, g, b } = parseHex(hex)
    return `\x1b[38;2;${r};${g};${b}m`
}

export function getPostHogHex(index: number): string {
    const wrapped = ((index % POSTHOG_COLORS.length) + POSTHOG_COLORS.length) % POSTHOG_COLORS.length
    return POSTHOG_COLORS[wrapped]
}

// Stride-thins labels to avoid collisions; the last label is always kept so the
// right edge of the chart stays anchored.
export function buildLabelRow(labels: unknown[], step: number): string {
    if (labels.length === 0) {
        return ''
    }
    const cleaned = labels.map((l) => stringify(l).replace(/-\d{4}$/, ''))
    const maxLen = Math.max(...cleaned.map((l) => l.length))
    const stride = Math.max(1, Math.ceil((maxLen + 1) / step))
    const rowWidth = Y_AXIS_PAD + (cleaned.length - 1) * step + maxLen + 2
    const row: string[] = new Array(rowWidth).fill(' ')
    cleaned.forEach((label, i) => {
        if (i % stride !== 0 && i !== cleaned.length - 1) {
            return
        }
        const center = Y_AXIS_PAD + i * step
        const start = Math.max(0, center - Math.floor(label.length / 2))
        for (let k = 0; k < label.length && start + k < row.length; k++) {
            row[start + k] = label[k]
        }
    })
    return row.join('').trimEnd()
}
