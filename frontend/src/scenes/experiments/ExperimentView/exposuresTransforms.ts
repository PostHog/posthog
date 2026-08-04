import type { Series } from '@posthog/quill-charts'

import { dayjs } from 'lib/dayjs'

import { ExperimentExposureTimeSeries } from '~/queries/schema/schema-general'

// Single-day timeseries get a synthetic prior day with 0 exposures so the chart
// can draw a line instead of a single point.
export function buildExposureSeries(timeseries: ExperimentExposureTimeSeries[]): {
    labels: string[]
    series: Series[]
} {
    let labels = timeseries[0].days
    let series: Series[] = timeseries.map((variantTimeseries) => ({
        key: variantTimeseries.variant,
        label: variantTimeseries.variant,
        data: variantTimeseries.exposure_counts,
    }))

    if (labels.length === 1) {
        labels = [dayjs(labels[0]).subtract(1, 'day').format('YYYY-MM-DD'), ...labels]
        series = series.map((variantSeries) => ({ ...variantSeries, data: [0, ...variantSeries.data] }))
    }

    return { labels, series }
}
