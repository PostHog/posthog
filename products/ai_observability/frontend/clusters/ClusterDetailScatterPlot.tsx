import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import { ScatterChart } from '@posthog/quill-charts'
import type { ScatterAreaSelection, ScatterChartConfig, ScatterPointDatum } from '@posthog/quill-charts'

import { makeChartErrorHandler } from 'lib/charts/chartErrorHandler'
import { useChartTheme } from 'lib/charts/hooks'

import { traceDrawerLogic } from '../redesign/trace/traceDrawerLogic'
import { clusterDetailLogic } from './clusterDetailLogic'
import { ClusterMapControls } from './ClusterMapControls'
import { navigateToClusterItem } from './clusterScatter'
import type { ClusterScatterMeta } from './clusterScatter'
import { ClusterDetailTooltip } from './ClusterScatterTooltip'
import { toClusterTraceDrawerRow } from './clusterTraceDrawerRow'

const handleChartError = makeChartErrorHandler('ai-cluster-detail-scatter')

export function ClusterDetailScatterPlot(): JSX.Element {
    const { cluster, traceSummaries, scatterPlotSeries, clusteringLevel, filteredItemIds, mapHighlight, mapSizeBy } =
        useValues(clusterDetailLogic)
    const { setMapHighlight, setMapSizeBy } = useActions(clusterDetailLogic)
    const { isEnabled } = useValues(traceDrawerLogic({ listId: 'cluster-traces' }))
    const { openRow } = useActions(traceDrawerLogic({ listId: 'cluster-traces' }))
    const theme = useChartTheme()
    const [zoom, setZoom] = useState<ScatterAreaSelection | null>(null)

    // Drop a pinned zoom when the data changes — a stale domain from the previous UMAP space would
    // drop the new points and render the plot blank until reset.
    useEffect(() => setZoom(null), [cluster, filteredItemIds])

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
        if (!meta) {
            return
        }
        if (meta.itemId && isEnabled && cluster?.traces[meta.itemId]) {
            const row = toClusterTraceDrawerRow(
                { traceId: meta.itemId, traceInfo: cluster.traces[meta.itemId], summary: traceSummaries[meta.itemId] },
                clusteringLevel
            )
            if (row) {
                openRow(row)
            }
            return
        }
        navigateToClusterItem(meta, clusteringLevel, traceSummaries)
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
        </div>
    )
}
