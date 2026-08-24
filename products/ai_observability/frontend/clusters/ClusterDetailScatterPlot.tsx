import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useMemo, useState } from 'react'

import { ScatterChart } from '@posthog/quill-charts'
import type { ScatterAreaSelection, ScatterChartConfig, ScatterPointDatum } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'

import { clusterDetailLogic } from './clusterDetailLogic'
import { clusterItemFooter, clusterItemLabel, navigateToClusterItem } from './clusterScatter'
import type { ClusterScatterMeta } from './clusterScatter'
import { ClusterScatterTooltip } from './ClusterScatterTooltip'

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
                            <ClusterScatterTooltip
                                color={point.color}
                                title="Cluster centroid"
                                subtitle="Center of this cluster"
                            />
                        )
                    }
                    return (
                        <ClusterScatterTooltip
                            color={point.color}
                            title={cluster?.title ?? point.seriesLabel}
                            subtitle={
                                clusterItemLabel(meta, clusteringLevel, traceSummaries) ??
                                fallbackItemLabel(meta, clusteringLevel)
                            }
                            footer={clusterItemFooter(meta, clusteringLevel)}
                        />
                    )
                }}
            />
        </div>
    )
}
