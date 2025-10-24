import { IconCheckCircle, IconWarning } from '@posthog/icons'

import { IconExclamation } from 'lib/lemon-ui/icons'
import { WebVitalsPercentile } from 'scenes/web-analytics/common'

import { WebVitalsItem, WebVitalsMetric, WebVitalsMetricBand } from '~/queries/schema/schema-general'

const PERCENTILE_NAME: Record<WebVitalsPercentile, string> = {
    p75: '75%',
    p90: '90%',
    p99: '99%',
}

export const LONG_METRIC_NAME: Record<WebVitalsMetric, string> = {
    INP: 'Interaction to Next Paint',
    LCP: 'Largest Contentful Paint',
    FCP: 'First Contentful Paint',
    CLS: 'Cumulative Layout Shift',
}

export const METRIC_DESCRIPTION: Record<WebVitalsMetric, string> = {
    INP: 'Measures the time it takes for the user to interact with the page and for the page to respond to the interaction. Lower is better.',
    LCP: 'Measures how long it takes for the main content of a page to appear on screen. Lower is better.',
    FCP: 'Measures how long it takes for the initial text, non-white background, and non-white text to appear on screen. Lower is better.',
    CLS: 'Measures how much the layout of a page shifts around as content loads. Lower is better.',
}

export const ICON_PER_BAND: Record<WebVitalsMetricBand, React.ElementType> = {
    good: IconCheckCircle,
    needs_improvements: IconWarning,
    poor: IconExclamation,
}

export const GRADE_PER_BAND: Record<WebVitalsMetricBand, string> = {
    good: 'Great',
    needs_improvements: 'Needs Improvement',
    poor: 'Poor',
}

export const POSITIONING_PER_BAND: Record<WebVitalsMetricBand, string> = {
    good: 'Below',
    needs_improvements: 'Between',
    poor: 'Above',
}

export const VALUES_PER_BAND: Record<WebVitalsMetricBand, (threshold: WebVitalsThreshold) => number[]> = {
    good: (threshold) => [threshold.good],
    needs_improvements: (threshold) => [threshold.good, threshold.poor],
    poor: (threshold) => [threshold.poor],
}

export const QUANTIFIER_PER_BAND: Record<WebVitalsMetricBand, (webVitalsPercentile: WebVitalsPercentile) => string> = {
    good: (webVitalsPercentile) => `More than ${PERCENTILE_NAME[webVitalsPercentile]} of visits had`,
    needs_improvements: (webVitalsPercentile) =>
        `Some of the ${PERCENTILE_NAME[webVitalsPercentile]} most performatic visits had`,
    poor: (webVitalsPercentile) => `Some of the ${PERCENTILE_NAME[webVitalsPercentile]} most performatic visits had`,
}

export const EXPERIENCE_PER_BAND: Record<WebVitalsMetricBand, string> = {
    good: 'a great experience',
    needs_improvements: 'an experience that needs improvement',
    poor: 'a poor experience',
}

export const getMetric = (
    results: WebVitalsItem[] | undefined,
    metric: WebVitalsMetric,
    percentile: WebVitalsPercentile
): number | undefined => {
    const data = results
        ?.filter((result) => result.action.custom_name === metric) // Filter to the right metric
        .find((result) => result.action.math === percentile)?.data // Get the right percentile // Get the actual data array

    if (!data || data.length === 0) {
        return undefined
    }

    // If CLS, return last value only if there's any non-zero data
    // (CLS can legitimately be 0, but if ALL values are 0, there's no data)
    if (metric === 'CLS') {
        const hasAnyData = data.some((value) => value !== 0)
        return hasAnyData ? data.slice(-1)[0] : undefined
    }

    // Else, return the last non-0 value
    return data.filter((value) => value !== 0).slice(-1)[0] // Get the last non-0 value
}

export const getMetricBand = (value: number | undefined, metric: WebVitalsMetric): WebVitalsMetricBand | 'none' => {
    const threshold = WEB_VITALS_THRESHOLDS[metric]

    if (value === undefined) {
        return 'none'
    }

    if (value <= threshold.good) {
        return 'good'
    }

    if (value <= threshold.poor) {
        return 'needs_improvements'
    }

    return 'poor'
}

type ValueWithUnit = { value: string | undefined; unit: 's' | 'ms' | undefined }
export const getValueWithUnit = (value: number | undefined, tab: WebVitalsMetric): ValueWithUnit => {
    if (value === undefined) {
        return { value: undefined, unit: undefined }
    }

    const inSeconds = tab !== 'CLS'
    if (inSeconds) {
        return value < 1000 ? { value: value.toFixed(0), unit: 'ms' } : { value: (value / 1000).toFixed(2), unit: 's' }
    }

    return { value: value.toFixed(2), unit: undefined }
}

export const getThresholdColor = (value: number | undefined, metric: WebVitalsMetric): string => {
    const threshold = WEB_VITALS_THRESHOLDS[metric]

    if (value === undefined) {
        return 'var(--color-gray-500)'
    }

    if (value <= threshold.good) {
        return WEB_VITALS_COLORS.good
    }

    if (value <= threshold.poor) {
        return WEB_VITALS_COLORS.needs_improvements
    }

    return WEB_VITALS_COLORS.poor
}

// Returns a value between 0 and 1 that represents the position of the value inside that band
//
// Useful to display the indicator line in the progress bar
// or the width of the segment in the path breakdown
export const computePositionInBand = (value: number, metric: WebVitalsMetric): number => {
    const threshold = WEB_VITALS_THRESHOLDS[metric]

    if (value <= threshold.good) {
        return value / threshold.good
    }

    // Values can be much higher than what we consider the end, so max out at 1
    if (value > threshold.poor) {
        return Math.min((value - threshold.poor) / (threshold.end - threshold.poor), 1)
    }

    return (value - threshold.good) / (threshold.poor - threshold.good)
}

// We're setting end to 20% above the poor threshold to have much more space in the UI for the good and poor segments
export type WebVitalsThreshold = { good: number; poor: number; end: number }
export const WEB_VITALS_THRESHOLDS: Record<WebVitalsMetric, WebVitalsThreshold> = {
    INP: { good: 200, poor: 500, end: 500 * 1.2 },
    LCP: { good: 2500, poor: 4000, end: 4000 * 1.2 },
    CLS: { good: 0.1, poor: 0.25, end: 0.25 * 1.2 },
    FCP: { good: 1800, poor: 3000, end: 3000 * 1.2 },
}

export const WEB_VITALS_COLORS = {
    good: 'var(--color-green-700)',
    needs_improvements: 'var(--color-amber-500)',
    poor: 'var(--color-red-700)',
} as const
