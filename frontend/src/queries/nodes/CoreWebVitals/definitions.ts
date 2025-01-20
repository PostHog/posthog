import { IconCheckCircle, IconWarning } from '@posthog/icons'
import { IconExclamation } from 'lib/lemon-ui/icons'
import { CoreWebVitalsPercentile, CoreWebVitalsThreshold } from 'scenes/web-analytics/webAnalyticsLogic'

import { CoreWebVitalsItem, CoreWebVitalsMetric } from '~/queries/schema'

type MetricBand = 'good' | 'improvements' | 'poor'

const PERCENTILE_NAME: Record<CoreWebVitalsPercentile, string> = {
    p75: '75%',
    p90: '90%',
    p99: '99%',
}

export const LONG_METRIC_NAME: Record<CoreWebVitalsMetric, string> = {
    INP: 'Interaction to Next Paint',
    LCP: 'Largest Contentful Paint',
    FCP: 'First Contentful Paint',
    CLS: 'Cumulative Layout Shift',
}

export const METRIC_DESCRIPTION: Record<CoreWebVitalsMetric, string> = {
    INP: 'Measures the time it takes for the user to interact with the page and for the page to respond to the interaction. Lower is better.',
    LCP: 'Measures how long it takes for the main content of a page to appear on screen. Lower is better.',
    FCP: 'Measures how long it takes for the initial text, non-white background, and non-white text to appear on screen. Lower is better.',
    CLS: 'Measures how much the layout of a page shifts around as content loads. Lower is better.',
}

export const ICON_PER_BAND: Record<MetricBand, React.ElementType> = {
    good: IconCheckCircle,
    improvements: IconWarning,
    poor: IconExclamation,
}

export const GRADE_PER_BAND: Record<MetricBand, string> = {
    good: 'Great',
    improvements: 'Needs Improvement',
    poor: 'Poor',
}

export const POSITIONING_PER_BAND: Record<MetricBand, string> = {
    good: 'Below',
    improvements: 'Between',
    poor: 'Above',
}

export const VALUES_PER_BAND: Record<MetricBand, (threshold: CoreWebVitalsThreshold) => number[]> = {
    good: (threshold) => [threshold.good],
    improvements: (threshold) => [threshold.good, threshold.poor],
    poor: (threshold) => [threshold.poor],
}

export const QUANTIFIER_PER_BAND: Record<MetricBand, (coreWebVitalsPercentile: CoreWebVitalsPercentile) => string> = {
    good: (coreWebVitalsPercentile) => `More than ${PERCENTILE_NAME[coreWebVitalsPercentile]} of visits had`,
    improvements: (coreWebVitalsPercentile) =>
        `Some of the ${PERCENTILE_NAME[coreWebVitalsPercentile]} most performatic visits had`,
    poor: (coreWebVitalsPercentile) =>
        `Some of the ${PERCENTILE_NAME[coreWebVitalsPercentile]} most performatic visits had`,
}

export const EXPERIENCE_PER_BAND: Record<MetricBand, string> = {
    good: 'a great experience',
    improvements: 'an experience that needs improvement',
    poor: 'a poor experience',
}

export const getMetric = (
    results: CoreWebVitalsItem[] | undefined,
    metric: CoreWebVitalsMetric,
    percentile: CoreWebVitalsPercentile
): number | undefined => {
    return results
        ?.filter((result) => result.action.custom_name === metric)
        .find((result) => result.action.math === percentile)
        ?.data.slice(-1)[0]
}

export const getMetricBand = (value: number | undefined, threshold: CoreWebVitalsThreshold): MetricBand | 'none' => {
    if (value === undefined) {
        return 'none'
    }

    if (value <= threshold.good) {
        return 'good'
    }

    if (value <= threshold.poor) {
        return 'improvements'
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
export const getThresholdColor = (value: number | undefined, threshold: CoreWebVitalsThreshold): Color => {
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
