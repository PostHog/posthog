import { useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import { ScatterChart } from '@posthog/quill-charts'
import type { ScatterAreaSelection, ScatterChartConfig, ScatterPointDatum } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'

import { makeChartErrorHandler } from 'products/product_analytics/frontend/insights/trends/shared/chartErrorHandler'

import { clusterDetailLogic } from './clusterDetailLogic'
import { navigateToClusterItem } from './clusterScatter'
import type { ClusterScatterMeta } from './clusterScatter'
import { ClusterDetailTooltip } from './ClusterScatterTooltip'

const handleChartError = makeChartErrorHandler('ai-cluster-detail-scatter')

export function ClusterDetailScatterPlot(): JSX.Element {
    const { cluster, traceSummaries, scatterPlotSeries, clusteringLevel } = useValues(clusterDetailLogic)
    const theme = useChartTheme()
    const [zoom, setZoom] = useState<ScatterAreaSelection | null>(null)

    // Drop a pinned zoom when the data changes — a stale domain from the previous UMAP space would
    // drop the new points and render the plot blank until reset.
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
                onError={handleChartError}
                tooltip={({ point }) => (
                    <ClusterDetailTooltip
                        point={point}
                        cluster={cluster}
                        clusteringLevel={clusteringLevel}
                        traceSummaries={traceSummaries}
                    />
                )}
            />
        </div>
    )
}
