import { useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useMemo, useState } from 'react'

import { ScatterChart } from '@posthog/quill-charts'
import type { ScatterAreaSelection, ScatterChartConfig, ScatterPointDatum } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { urls } from 'scenes/urls'

import { makeChartErrorHandler } from 'products/product_analytics/frontend/insights/trends/shared/chartErrorHandler'

import { navigateToClusterItem } from './clusterScatter'
import type { ClusterScatterMeta } from './clusterScatter'
import { ClusterOverviewTooltip } from './ClusterScatterTooltip'
import { clustersLogic } from './clustersLogic'

const handleChartError = makeChartErrorHandler('ai-clusters-scatter')

export function ClusterScatterPlot(): JSX.Element {
    const { scatterPlotSeries, sortedClusters, effectiveRunId, clusteringLevel, traceSummaries } =
        useValues(clustersLogic)
    const theme = useChartTheme()
    const [zoom, setZoom] = useState<ScatterAreaSelection | null>(null)

    // Drop a pinned zoom when the data changes (run switch or filter) — a stale domain from the
    // previous run's UMAP space would drop the new points and render the plot blank until reset.
    useEffect(() => setZoom(null), [scatterPlotSeries])

    const config = useMemo<ScatterChartConfig<ClusterScatterMeta>>(
        () => ({
            xAxis: { hide: true, domain: zoom?.x },
            yAxis: { hide: true, domain: zoom?.y },
            tooltip: { placement: 'cursor' },
        }),
        [zoom]
    )

    const handlePointClick = (point: ScatterPointDatum<ClusterScatterMeta>): void => {
        if (point.meta?.isCentroid) {
            if (point.meta.clusterId !== undefined && effectiveRunId) {
                router.actions.push(urls.aiObservabilityCluster(effectiveRunId, point.meta.clusterId))
            }
            return
        }
        if (point.meta) {
            navigateToClusterItem(point.meta, clusteringLevel, traceSummaries)
        }
    }

    if (sortedClusters.length === 0) {
        return <div className="text-muted text-center py-8">No cluster data available for visualization</div>
    }

    return (
        <div className="h-80 flex flex-col" onDoubleClick={() => setZoom(null)}>
            <ScatterChart
                series={scatterPlotSeries}
                theme={theme}
                config={config}
                dataAttr="ai-clusters-scatter"
                onPointClick={handlePointClick}
                onAreaSelect={setZoom}
                onError={handleChartError}
                tooltip={({ point }) => (
                    <ClusterOverviewTooltip
                        point={point}
                        clusteringLevel={clusteringLevel}
                        traceSummaries={traceSummaries}
                    />
                )}
            />
        </div>
    )
}
