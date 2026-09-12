import type { Series } from '@posthog/quill-charts'

import { dayjs } from 'lib/dayjs'

import { ExperimentExposureTimeSeries, SampleRatioMismatch } from '~/queries/schema/schema-general'

export function buildExposureSeries(timeseries: ExperimentExposureTimeSeries[]): {
    labels: string[]
    series: Series[]
} {
    if (!timeseries.length) {
        return { labels: [], series: [] }
    }

    let labels = timeseries[0].days
    let series: Series[] = timeseries.map((variantTimeseries) => ({
        key: variantTimeseries.variant,
        label: variantTimeseries.variant,
        data: variantTimeseries.exposure_counts,
    }))

    // A single point draws nothing, so give it a zeroed prior day to draw a line from.
    if (labels.length === 1) {
        labels = [dayjs(labels[0]).subtract(1, 'day').format('YYYY-MM-DD'), ...labels]
        series = series.map((variantSeries) => ({ ...variantSeries, data: [0, ...variantSeries.data] }))
    }

    return { labels, series }
}

/**
 * `mismatch` is the long-standing SRM threshold. `borderline` and `dailyDrift` are
 * evidence that the split is off without being conclusive, so they must not read as
 * a clean bill of health.
 */
export type SrmStatus = 'mismatch' | 'borderline' | 'dailyDrift' | 'healthy'

const SRM_MISMATCH_P_VALUE = 0.001
const SRM_BORDERLINE_P_VALUE = 0.05

export function getSrmStatus(sampleRatioMismatch: SampleRatioMismatch): SrmStatus {
    if (sampleRatioMismatch.p_value < SRM_MISMATCH_P_VALUE) {
        return 'mismatch'
    }
    if (sampleRatioMismatch.p_value < SRM_BORDERLINE_P_VALUE) {
        return 'borderline'
    }
    // Cumulative totals can hide a variant that runs hot on some days and cold on
    // others, because the two errors cancel. The daily test still sees it.
    if (sampleRatioMismatch.daily != null && sampleRatioMismatch.daily.p_value < SRM_BORDERLINE_P_VALUE) {
        return 'dailyDrift'
    }
    return 'healthy'
}
