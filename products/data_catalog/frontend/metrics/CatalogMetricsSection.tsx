import { useActions, useValues } from 'kea'

import { Skeleton } from '@posthog/quill'

import { ModelsOverviewErrorCallout } from 'products/data_modeling/frontend/ModelsOverviewErrorCallout'
import { dataQualityOverviewLogic } from 'products/data_quality/frontend/overview/dataQualityOverviewLogic'

import { metricsLogic } from '../metricsLogic'
import { CatalogMetricsBulkBar } from './CatalogMetricsBulkBar'
import { catalogMetricsLogic } from './catalogMetricsLogic'
import { CatalogMetricsTable } from './CatalogMetricsTable'
import { CatalogMetricsToolbar } from './CatalogMetricsToolbar'

const SKELETON_ROWS = 5

function LoadingRows(): JSX.Element {
    return (
        <div className="flex flex-col gap-2" aria-busy="true">
            {Array.from({ length: SKELETON_ROWS }, (_, index) => (
                <Skeleton key={index} className="h-10 w-full" />
            ))}
        </div>
    )
}

function ChecksLoadError(): JSX.Element | null {
    const { overviewError } = useValues(dataQualityOverviewLogic)
    const { loadOverview } = useActions(dataQualityOverviewLogic)
    if (!overviewError) {
        return null
    }
    return (
        <ModelsOverviewErrorCallout
            message="Data quality checks could not be loaded, so the Checks column may be out of date."
            onRetry={() => loadOverview()}
            dataAttr="data-catalog-metrics-checks-error"
        />
    )
}

function MetricsContent(): JSX.Element {
    const { allMetrics, allMetricsLoading, metricsLoadState } = useValues(metricsLogic)
    const { loadMetrics } = useActions(metricsLogic)
    if (allMetrics.length > 0) {
        return <CatalogMetricsTable />
    }
    if (allMetricsLoading) {
        return <LoadingRows />
    }
    if (metricsLoadState === 'failed') {
        return (
            <ModelsOverviewErrorCallout
                message="Metrics could not be loaded."
                onRetry={() => loadMetrics()}
                dataAttr="data-catalog-metrics-load-error"
            />
        )
    }
    return <CatalogMetricsTable />
}

export function CatalogMetricsSection(): JSX.Element {
    const { selectedMetricIds } = useValues(catalogMetricsLogic)

    return (
        <section aria-label="Metrics" className="flex flex-col gap-3" data-attr="data-catalog-metrics">
            <CatalogMetricsToolbar />
            <ChecksLoadError />
            <MetricsContent />
            {selectedMetricIds.length > 0 && <CatalogMetricsBulkBar />}
        </section>
    )
}
