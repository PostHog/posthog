import type { DataFrame } from './frame'
import { bucketEnd } from './frames'

export interface DrillContext {
    refId?: string
    series?: { name: string; labels?: Record<string, string> }
    value?: unknown
    time?: { from: number; to: number }
    row?: Record<string, unknown>
    category?: string
    step?: { index: number; name: string; dropoff?: boolean }
    cohort?: { index: number; label: string; period?: number }
    node?: string
}

export function seriesOrigin(frames: DataFrame[], key: string): { refId?: string; labels?: Record<string, string> } {
    const [frameIndex, numberIndex] = key.split(':').map(Number)
    const frame = frames[frameIndex ?? -1]
    return {
        refId: frame?.refId,
        labels: frame?.fields.filter((field) => field.type === 'number')[numberIndex ?? 0]?.labels,
    }
}

export function bucketOf(labels: string[], index: number): { from: number; to: number } | undefined {
    const start = Date.parse(labels[index] ?? '')
    if (!Number.isFinite(start)) {
        return undefined
    }
    const next = Date.parse(labels[index + 1] ?? '')
    const end = bucketEnd(labels.map((label) => Date.parse(label)))
    return { from: start, to: Number.isFinite(next) ? next : end ? end(start) : start + 60_000 }
}
