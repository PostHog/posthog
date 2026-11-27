import { useActions, useValues } from 'kea'

import { Skeleton, cn } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { userHasAccess } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { ModelsOverviewErrorCallout } from 'products/data_modeling/frontend/ModelsOverviewErrorCallout'
import { dataQualityOverviewLogic } from 'products/data_quality/frontend/overview/dataQualityOverviewLogic'

import { QuillCatalogSetupBanner } from '../components/QuillCatalogSetupBanner'
import { metricsIntroLogic } from '../metricsIntroLogic'
import { metricsLogic } from '../metricsLogic'
import { usageLogic } from '../usageLogic'
import { CatalogMetricsBulkBar } from './CatalogMetricsBulkBar'
import { CatalogMetricsEmptyState } from './CatalogMetricsEmptyState'
import { CatalogMetricsLayers } from './CatalogMetricsLayers'
import { catalogMetricsLogic } from './catalogMetricsLogic'
import { CatalogMetricsTable } from './CatalogMetricsTable'
import { CatalogMetricsToolbar } from './CatalogMetricsToolbar'
import { CatalogSuggestedMetrics } from './CatalogSuggestedMetrics'
import { MetricsIntroStrip } from './MetricsIntroStrip'

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

function MetricsContent({ layered }: { layered: boolean }): JSX.Element {
    const { allMetrics, allMetricsLoading, metricsLoadState } = useValues(metricsLogic)
    const { loadMetrics } = useActions(metricsLogic)
    if (allMetrics.length > 0) {
        return layered ? <CatalogMetricsLayers /> : <CatalogMetricsTable list="all" />
    }
    // The empty state reloads metrics on each window focus. Keeping it mounted through that reload
    // stops a skeleton flash and a repeat impression event.
    if (metricsLoadState === 'loaded') {
        return <CatalogMetricsEmptyState />
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
    return <LoadingRows />
}

function SuggestionsToolbar(): JSX.Element | null {
    const { proposedRows } = useValues(usageLogic)
    return proposedRows.length > 0 ? <CatalogMetricsToolbar /> : null
}

function MetricsNotice(): JSX.Element | null {
    const { metricsNotice } = useValues(metricsIntroLogic)
    if (metricsNotice === 'intro') {
        return <MetricsIntroStrip />
    }
    return metricsNotice === 'setup' ? <QuillCatalogSetupBanner /> : null
}

export function CatalogMetricsSection(): JSX.Element {
    const { selectedMetricIds } = useValues(catalogMetricsLogic)
    const { catalogEmpty } = useValues(metricsLogic)
    // The usage flag turns one long list into short lists: suggested, proposed, then approved metrics.
    const layered = useFeatureFlag('DATA_CATALOG_USAGE')
    // A suggestion shows SQL over warehouse tables, so it needs the access that the usage scan results need.
    const suggestionsAvailable =
        layered && userHasAccess(AccessControlResourceType.WarehouseObjects, AccessControlLevel.Viewer)

    return (
        <section aria-label="Metrics" className="flex flex-col gap-3" data-attr="data-catalog-metrics">
            <MetricsNotice />
            {/* Search and filters have nothing to act on in an empty catalog that has no suggestions. */}
            {catalogEmpty ? suggestionsAvailable && <SuggestionsToolbar /> : <CatalogMetricsToolbar />}
            <ChecksLoadError />
            {/* The padded last row of each table adds to the gap above the next heading. This padding gives the
                first heading the same visible space below the toolbar. */}
            <div className={cn('flex flex-col gap-6', layered && 'pt-5')}>
                {suggestionsAvailable && <CatalogSuggestedMetrics />}
                <MetricsContent layered={layered} />
            </div>
            {selectedMetricIds.length > 0 && <CatalogMetricsBulkBar />}
        </section>
    )
}
