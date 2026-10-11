import { buildPagePerformancePathExpr } from 'scenes/web-analytics/pagePerformanceLogic'

import { WebVitalsMetric, WebVitalsPercentile } from '~/queries/schema/schema-general'
import { escapeHogQLString } from '~/queries/utils'
import { PropertyMathType } from '~/types'

import { WEB_VITALS_THRESHOLDS, getValueWithUnit } from './definitions'

interface AttributionColumn {
    label: string
    field: string
}

interface AttributionConfig {
    // The attribution field that holds the CSS selector of the element behind the metric
    element: string
    groupBy: AttributionColumn[]
    // Timing fields in milliseconds, shown at the selected percentile
    phases: AttributionColumn[]
}

// Mirrors the attribution fields posthog-js keeps on `$web_vitals_<metric>_event.attribution`.
// FCP has no element attribution, so it has no drill-down.
export const WEB_VITALS_ATTRIBUTION: Partial<Record<WebVitalsMetric, AttributionConfig>> = {
    INP: {
        element: 'interactionTarget',
        groupBy: [{ label: 'Interaction', field: 'interactionType' }],
        phases: [
            { label: 'Input delay', field: 'inputDelay' },
            { label: 'Processing', field: 'processingDuration' },
            { label: 'Presentation delay', field: 'presentationDelay' },
        ],
    },
    LCP: {
        element: 'target',
        groupBy: [{ label: 'Resource', field: 'url' }],
        phases: [
            { label: 'Time to first byte', field: 'timeToFirstByte' },
            { label: 'Resource load delay', field: 'resourceLoadDelay' },
            { label: 'Resource load duration', field: 'resourceLoadDuration' },
            { label: 'Element render delay', field: 'elementRenderDelay' },
        ],
    },
    CLS: {
        element: 'largestShiftTarget',
        groupBy: [],
        phases: [],
    },
}

const PERCENTILE_LEVEL: Record<WebVitalsPercentile, number> = {
    [PropertyMathType.P75]: 0.75,
    [PropertyMathType.P90]: 0.9,
    [PropertyMathType.P99]: 0.99,
}

export const hasWebVitalsAttribution = (metric: WebVitalsMetric): boolean => !!WEB_VITALS_ATTRIBUTION[metric]

export const buildWebVitalsAttributionQuery = ({
    metric,
    percentile,
    path,
    isPathCleaningEnabled,
    pathCleaningFilters,
}: {
    metric: WebVitalsMetric
    percentile: WebVitalsPercentile
    path: string
    isPathCleaningEnabled: boolean
    pathCleaningFilters: { regex?: string; alias?: string }[] | undefined
}): string | null => {
    const config = WEB_VITALS_ATTRIBUTION[metric]
    if (!config) {
        return null
    }

    const attribution = (field: string): string => `properties.$web_vitals_${metric}_event.attribution.${field}`
    const value = `toFloat(properties.$web_vitals_${metric}_value)`
    const quantile = `quantile(${PERCENTILE_LEVEL[percentile]})`
    const element = attribution(config.element)
    const pathExpr = buildPagePerformancePathExpr('properties.$pathname', isPathCleaningEnabled, pathCleaningFilters)
    const goodThreshold = WEB_VITALS_THRESHOLDS[metric].good
    const { value: goodValue, unit: goodUnit } = getValueWithUnit(goodThreshold, metric)
    const aboveGood = `Above ${goodValue}${goodUnit ?? ''}`

    const columns = [
        `${element} AS "Element"`,
        ...config.groupBy.map(({ label, field }) => `${attribution(field)} AS "${label}"`),
        `count() AS "Events"`,
        `countIf(${value} > ${goodThreshold}) AS "${aboveGood}"`,
        `round(${quantile}(${value}), ${metric === 'CLS' ? 3 : 0}) AS "${metric}"`,
        ...config.phases.map(({ label, field }) => `round(${quantile}(toFloat(${attribution(field)}))) AS "${label}"`),
    ]
    const groupBy = ['"Element"', ...config.groupBy.map(({ label }) => `"${label}"`)]

    return `SELECT
    ${columns.join(',\n    ')}
FROM events
WHERE and(
    event = '$web_vitals',
    ${pathExpr} = ${escapeHogQLString(path)},
    ${element} IS NOT NULL,
    ${element} != '',
    {filters}
)
GROUP BY ${groupBy.join(', ')}
ORDER BY "${aboveGood}" DESC, "Events" DESC
LIMIT 50`
}
