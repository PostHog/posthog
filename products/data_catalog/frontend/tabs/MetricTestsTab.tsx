import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { DataQualityChecksPanel } from 'products/data_quality/frontend/DataQualityChecksPanel'

import { dataCatalogMetricSceneLogic } from '../dataCatalogMetricSceneLogic'

export function MetricTestsTab(): JSX.Element | null {
    const { metric, supportsMetricChecks } = useValues(dataCatalogMetricSceneLogic)

    if (!metric) {
        return null
    }
    if (!supportsMetricChecks) {
        return (
            <LemonBanner type="info">
                Tests are available for SQL metrics only. Save a HogQL query as this metric's definition to add checks.
            </LemonBanner>
        )
    }

    return <DataQualityChecksPanel subjectType="metric" subjectId={metric.id} columns={[]} hideTitle />
}
