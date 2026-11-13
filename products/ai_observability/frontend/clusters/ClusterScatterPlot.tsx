import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import { ScatterChart } from '@posthog/quill-charts'
import type { ScatterAreaSelection, ScatterChartConfig, ScatterPointDatum } from '@posthog/quill-charts'

import { makeChartErrorHandler } from 'lib/charts/chartErrorHandler'
import { useChartTheme } from 'lib/charts/hooks'

import { traceDrawerLogic } from '../redesign/trace/traceDrawerLogic'
import { ClusterMapControls } from './ClusterMapControls'
import { navigateToClusterItem } from './clusterScatter'
import type { ClusterScatterMeta } from './clusterScatter'
import { ClusterOverviewTooltip } from './ClusterScatterTooltip'
import { clustersLogic } from './clustersLogic'
import { toClusterTraceDrawerRow } from './clusterTraceDrawerRow'

const handleChartError = makeChartErrorHandler('ai-clusters-scatter')

export function ClusterScatterPlot(): JSX.Element {
    const {
        scatterPlotSeries,
        sortedClusters,
        filteredSortedClusters,
        clusteringLevel,
        traceSummaries,
        mapSizeBy,
        mapHighlight,
    } = useValues(clustersLogic)
    const { setMapSizeBy, setMapHighlight } = useActions(clustersLogic)
    const { isEnabled } = useValues(traceDrawerLogic({ listId: 'clusters' }))
    const { openRow } = useActions(traceDrawerLogic({ listId: 'clusters' }))
    const theme = useChartTheme()
    const [zoom, setZoom] = useState<ScatterAreaSelection | null>(null)

    // Drop a pinned zoom when the data changes (run switch or filter) — a stale domain from the
    // previous run's UMAP space would drop the new points and render the plot blank until reset.
    useEffect(() => setZoom(null), [filteredSortedClusters])

    const config = useMemo<ScatterChartConfig<ClusterScatterMeta>>(
        () => ({
            xAxis: { hide: true, domain: zoom?.x },
            yAxis: { hide: true, domain: zoom?.y },
            tooltip: { placement: 'cursor' },
        }),
        [zoom]
    )

    const handlePointClick = (point: ScatterPointDatum<ClusterScatterMeta>): void => {
        const meta = point.meta
        if (meta?.itemId && isEnabled) {
            const info = sortedClusters.find((cluster) => cluster.cluster_id === meta.clusterId)?.traces[meta.itemId]
            if (info) {
                const row = toClusterTraceDrawerRow(
                    { traceId: meta.itemId, traceInfo: info, summary: traceSummaries[meta.itemId] },
                    clusteringLevel
                )
                if (row) {
                    openRow(row)
                }
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
        <div>
            <ClusterMapControls
                highlight={mapHighlight}
                sizeBy={mapSizeBy}
                onHighlightChange={setMapHighlight}
                onSizeChange={setMapSizeBy}
            />
            <div className="h-96 flex flex-col" onDoubleClick={() => setZoom(null)}>
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
        </div>
    )
}
