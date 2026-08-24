import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useMemo, useState } from 'react'

import { ScatterChart, TooltipFooter, TooltipSurface, TooltipSwatch } from '@posthog/quill-charts'
import type { ScatterAreaSelection, ScatterChartConfig, ScatterPointDatum } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'

import { clusterDetailLogic } from './clusterDetailLogic'
import { clusterItemFooter, clusterItemLabel, navigateToClusterItem } from './clusterScatter'
import type { ClusterScatterMeta } from './clusterScatter'

/** Falls back to a shortened id when the trace/eval summary hasn't loaded yet. */
function fallbackItemLabel(meta: ClusterScatterMeta, clusteringLevel: string): string | undefined {
    if (!meta.traceId) {
        return undefined
    }
    const id = (meta.generationId || meta.traceId).slice(0, 8)
    if (clusteringLevel === 'generation') {
        return `Generation ${id}...`
    }
    if (clusteringLevel === 'evaluation') {
        return `Evaluation ${id}...`
    }
    return `Trace ${meta.traceId.slice(0, 8)}...`
}

export function ClusterDetailScatterPlot(): JSX.Element {
    const { cluster, traceSummaries, scatterPlotSeries, clusteringLevel } = useValues(clusterDetailLogic)
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
        if (point.meta?.isCentroid || !point.meta) {
            return
        }
        navigateToClusterItem(point.meta, clusteringLevel, traceSummaries)
    }

    return (
        <div className="h-64 flex flex-col" onDoubleClick={() => setZoom(null)}>
            <ScatterChart
                series={scatterPlotSeries}
                theme={theme}
                config={config}
                dataAttr="ai-cluster-detail-scatter"
                onPointClick={handlePointClick}
                onAreaSelect={setZoom}
                onError={(error, info) =>
                    posthog.captureException(error, {
                        feature: 'ai-cluster-detail-scatter',
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
                                    <span className="truncate">Cluster centroid</span>
                                </div>
                                <div className="opacity-60">Center of this cluster</div>
                            </TooltipSurface>
                        )
                    }
                    const body =
                        clusterItemLabel(meta, clusteringLevel, traceSummaries) ??
                        fallbackItemLabel(meta, clusteringLevel)
                    const footer = clusterItemFooter(meta, clusteringLevel)
                    return (
                        <TooltipSurface>
                            <div className="flex items-center gap-2 min-w-0 font-semibold">
                                <TooltipSwatch color={point.color} />
                                <span className="truncate">{cluster?.title ?? point.seriesLabel}</span>
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
