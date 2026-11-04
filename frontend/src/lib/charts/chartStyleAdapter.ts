import type { ChartStyle } from '~/queries/schema/schema-general'

// The schema vocabulary is 'smooth'/'linear'; quill's chart config calls the same shapes
// 'monotone'/'linear', so 'smooth' maps to 'monotone'. Unset falls through to the app default.
export function chartStyleCurve(chartStyle: ChartStyle | null | undefined): 'linear' | 'monotone' | undefined {
    if (!chartStyle?.curve) {
        return undefined
    }
    return chartStyle.curve === 'smooth' ? 'monotone' : 'linear'
}
