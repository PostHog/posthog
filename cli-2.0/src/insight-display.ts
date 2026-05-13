// Pure helpers shared by the insight terminal renderer — no I/O so they can
// be unit-tested.

export type JsonRecord = Record<string, unknown>

export type ChartSeries = JsonRecord & { data: unknown[]; labels: unknown[] }

export const Y_AXIS_PAD = 7
const MAX_STEP = 12

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
  if (abs >= 1_000_000) {
    return `${(x / 1_000_000).toFixed(1)}M`
  }
  if (abs >= 10_000) {
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
