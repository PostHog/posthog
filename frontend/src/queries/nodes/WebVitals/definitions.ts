import { IconCheckCircle, IconWarning } from '@posthog/icons'
import { IconExclamation } from 'lib/lemon-ui/icons'
import { WebVitalsPercentile, WebVitalsThreshold } from 'scenes/web-analytics/webAnalyticsLogic'

import { WebVitalsItem, WebVitalsMetric, WebVitalsMetricBand } from '~/queries/schema'

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
    return results
        ?.filter((result) => result.action.custom_name === metric)
        .find((result) => result.action.math === percentile)
        ?.data.slice(-1)[0]
}

export const getMetricBand = (
    value: number | undefined,
    threshold: WebVitalsThreshold
): WebVitalsMetricBand | 'none' => {
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
export const getValueWithUnit = (value: number | undefined, inSeconds: boolean): ValueWithUnit => {
    if (value === undefined) {
        return { value: undefined, unit: undefined }
    }

    // Use a dash to represent lack of value, it's unlikely that a metric will be 0
    if (value === 0) {
        return { value: '-', unit: undefined }
    }

    if (inSeconds) {
        return value < 1000 ? { value: value.toFixed(0), unit: 'ms' } : { value: (value / 1000).toFixed(2), unit: 's' }
    }

    return { value: value.toFixed(2), unit: undefined }
}

type Color = 'muted' | 'success' | 'warning' | 'danger'
export const getThresholdColor = (value: number | undefined, threshold: WebVitalsThreshold): Color => {
    if (value === undefined) {
        return 'muted'
    }

    if (value <= threshold.good) {
        return 'success'
    }

    if (value <= threshold.poor) {
        return 'warning'
    }

    return 'danger'
}
