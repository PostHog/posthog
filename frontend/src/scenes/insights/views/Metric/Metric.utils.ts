import { type MetricChange } from '@posthog/quill-charts'

// Above this magnitude the exact percentage is noise (it comes from a near-zero start), so show ∞ instead.
export const MAX_CHANGE_PERCENT = 10_000 // ≈100×

// Defaults for the Metric display options (kept here so the view and the editor filters share one source).
export const METRIC_SHOW_CHANGE_DEFAULT = true
export const METRIC_COLOR_BY_DIRECTION_DEFAULT = false
export const METRIC_DEFAULT_INCREASE_COLOR = '#388600'
export const METRIC_DEFAULT_DECREASE_COLOR = '#db3707'

export interface MetricChangeResult {
    // `undefined` → no pill (fewer than two finite points); `null` → no movement worth showing.
    change: MetricChange | null | undefined
    // First finite value of the period, for the "vs … at start" subtitle.
    startValue: number | undefined
}

// The Metric pill and line both measure the change ACROSS the displayed period: first finite point → last finite
// point. A change from a zero start is infinite, and a near-zero start produces an absurd number, so render ∞ in
// those cases — the sign of `value` still drives the arrow + color.
export function computeMetricChange(data: number[] | undefined): MetricChangeResult {
    const finite = (data ?? []).filter((value) => Number.isFinite(value))
    if (finite.length < 2) {
        return { change: undefined, startValue: undefined }
    }
    const startValue = finite[0]
    const endValue = finite[finite.length - 1]
    if (startValue === 0) {
        const change = endValue === 0 ? null : { value: endValue > 0 ? 1 : -1, label: '∞' }
        return { change, startValue }
    }
    const percent = ((endValue - startValue) / Math.abs(startValue)) * 100
    const change = Math.abs(percent) >= MAX_CHANGE_PERCENT ? { value: percent, label: '∞' } : { value: percent }
    return { change, startValue }
}
