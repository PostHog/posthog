import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useMemo, useState } from 'react'

import { ScatterChart } from '@posthog/quill-charts'
import type { ScatterAreaSelection, ScatterChartConfig, ScatterPointDatum } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'

import { clusterDetailLogic } from './clusterDetailLogic'
import { navigateToClusterItem } from './clusterScatter'
import type { ClusterScatterMeta } from './clusterScatter'
import { ClusterDetailTooltip } from './ClusterScatterTooltip'

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
