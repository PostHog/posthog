import { useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'
import { useMemo, useState } from 'react'

import { ScatterChart } from '@posthog/quill-charts'
import type { ScatterAreaSelection, ScatterChartConfig, ScatterPointDatum } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { urls } from 'scenes/urls'

import { clusterItemFooter, clusterItemLabel, navigateToClusterItem } from './clusterScatter'
import type { ClusterScatterMeta } from './clusterScatter'
import { ClusterScatterTooltip } from './ClusterScatterTooltip'
import { clustersLogic } from './clustersLogic'

export function ClusterScatterPlot(): JSX.Element {
    const { scatterPlotSeries, sortedClusters, effectiveRunId, clusteringLevel, traceSummaries } =
        useValues(clustersLogic)
    const theme = useChartTheme()
    const [zoom, setZoom] = useState<ScatterAreaSelection | null>(null)

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
                onError={(error, info) =>
                    posthog.captureException(error, {
                        feature: 'ai-clusters-scatter',
                        componentStack: info.componentStack ?? undefined,
                    })
                }
                tooltip={({ point }) => {
                    const meta = point.meta ?? {}
                    if (meta.isCentroid) {
                        return (
                            <ClusterScatterTooltip
                                color={point.color}
                                title={point.seriesLabel.replace(' (centroid)', '')}
                                subtitle="Cluster centroid"
                                footer="click to view cluster"
                            />
                        )
                    }
                    return (
                        <ClusterScatterTooltip
                            color={point.color}
                            title={point.seriesLabel}
                            subtitle={clusterItemLabel(meta, clusteringLevel, traceSummaries)}
                            footer={clusterItemFooter(meta, clusteringLevel)}
                        />
                    )
                }}
            />
        </div>
    )
}
