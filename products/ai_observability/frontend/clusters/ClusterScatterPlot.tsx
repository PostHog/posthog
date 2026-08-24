import { useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'
import { useMemo, useState } from 'react'

import { ScatterChart, TooltipFooter, TooltipSurface, TooltipSwatch } from '@posthog/quill-charts'
import type { ScatterAreaSelection, ScatterChartConfig, ScatterPointDatum } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { urls } from 'scenes/urls'

import { clusterItemFooter, clusterItemLabel, navigateToClusterItem } from './clusterScatter'
import type { ClusterScatterMeta } from './clusterScatter'
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
                            <TooltipSurface>
                                <div className="flex items-center gap-2 min-w-0 font-semibold">
                                    <TooltipSwatch color={point.color} />
                                    <span className="truncate">{point.seriesLabel.replace(' (centroid)', '')}</span>
                                </div>
                                <div className="opacity-60">Cluster centroid</div>
                                <TooltipFooter>click to view cluster</TooltipFooter>
                            </TooltipSurface>
                        )
                    }
                    const body = clusterItemLabel(meta, clusteringLevel, traceSummaries)
                    const footer = clusterItemFooter(meta, clusteringLevel)
                    return (
                        <TooltipSurface>
                            <div className="flex items-center gap-2 min-w-0 font-semibold">
                                <TooltipSwatch color={point.color} />
                                <span className="truncate">{point.seriesLabel}</span>
                            </div>
                            {body ? <div className="opacity-60">{body}</div> : null}
                            {footer ? <TooltipFooter>{footer}</TooltipFooter> : null}
                        </TooltipSurface>
                    )
                }}
            />
        </div>
    )
}
