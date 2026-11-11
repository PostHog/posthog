import type { Series } from '@posthog/quill-charts'

import { dayjs } from 'lib/dayjs'

import { ExperimentExposureCriteria, ExperimentExposureTimeSeries } from '~/queries/schema/schema-general'

import { getActivationConfig, isDefaultExposureConfig } from '../exposureContract'
import { getExposureConfigDisplayName } from '../utils'

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

export function getExposureCriteriaLabel(
    exposureCriteria: ExperimentExposureCriteria | undefined,
    defaultEvent: string
): string {
    const activationConfig = getActivationConfig(exposureCriteria)
    if (activationConfig) {
        return `Default (${defaultEvent}) + activation (${getExposureConfigDisplayName(activationConfig)})`
    }

    const exposureConfig = exposureCriteria?.exposure_config
    if (!exposureConfig) {
        return `Default (${defaultEvent})`
    }
    if (isDefaultExposureConfig(exposureConfig)) {
        const hasFilters = 'properties' in exposureConfig && (exposureConfig.properties?.length ?? 0) > 0
        return hasFilters ? `Default (${defaultEvent}), with filters` : `Default (${defaultEvent})`
    }

    const displayName = getExposureConfigDisplayName(exposureConfig)
    return `Custom (${displayName})`
}
