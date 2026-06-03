import { BindLogic } from 'kea'
import { useMemo } from 'react'

import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { ActionsHorizontalBar } from 'scenes/trends/viz/ActionsHorizontalBar'
import { ActionsLineGraph } from 'scenes/trends/viz/ActionsLineGraph'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import type { DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { ChartDisplayType } from '~/types'
import type { InsightLogicProps } from '~/types'

import { TrendsBarChart } from 'products/product_analytics/frontend/insights/trends/TrendsBarChart/TrendsBarChart'
import { TrendsLineChart } from 'products/product_analytics/frontend/insights/trends/TrendsLineChart/TrendsLineChart'

import { buildCachedInsight } from './buildCachedInsight'
import type { BenchData } from './generateBenchData'

type AdapterKind =
    | 'adapter-hog'
    | 'adapter-chartjs'
    | 'adapter-bar'
    | 'adapter-bar-horizontal'
    | 'adapter-chartjs-bar'
    | 'adapter-chartjs-bar-horizontal'

/** Display type each bar adapter kind drives the insight with. hog and chart.js bar adapters share
 *  a display so they're a clean engine-vs-engine comparison; only the rendered component differs. */
const ADAPTER_BAR_DISPLAY: Partial<Record<AdapterKind, ChartDisplayType>> = {
    'adapter-bar': ChartDisplayType.ActionsBar,
    'adapter-bar-horizontal': ChartDisplayType.ActionsBarValue,
    'adapter-chartjs-bar': ChartDisplayType.ActionsBar,
    'adapter-chartjs-bar-horizontal': ChartDisplayType.ActionsBarValue,
}

interface RealAdaptersCellProps {
    kind: AdapterKind
    data: BenchData
    runKey: number
    fillArea: boolean
    /** Forwarded to the hog-charts bar adapter to A/B the tooltip's hover cost. Only affects
     *  `adapter-bar` / `adapter-bar-horizontal`; the chart.js adapters have no equivalent hook. */
    tooltipEnabled: boolean
}

/**
 * Mounts the real insight kea logic tree with synthetic cached data and
 * renders either the chart.js-based `ActionsLineGraph` or the hog-charts-based
 * `TrendsLineChart`. No HTTP — `dataNodeLogic` picks up `cachedResults` in
 * its `afterMount`/`propsChanged` hooks and calls `setResponse` directly,
 * so the insight pipeline sees our data as if it came from the API.
 *
 * Each runKey bump yields a fresh `dashboardItemId`, which produces fresh
 * kea logic instances (keyed off `dashboardItemId` via
 * `keyForInsightLogicProps`) so mount-time measurements aren't biased by
 * re-using a warm logic cache.
 */
export function RealAdaptersCell({ kind, data, runKey, fillArea, tooltipEnabled }: RealAdaptersCellProps): JSX.Element {
    const built = useMemo(
        () =>
            buildCachedInsight(data, {
                fillArea,
                display: ADAPTER_BAR_DISPLAY[kind],
            }),
        [data, fillArea, kind]
    )

    const insightProps: InsightLogicProps = useMemo(
        () => ({
            dashboardItemId: `new-AdHoc.chart-bench-${runKey}`,
            query: built.query,
            cachedInsight: built.cachedInsight,
            doNotLoad: true,
            dataNodeCollectionId: `chart-bench-${runKey}`,
        }),
        [built.query, built.cachedInsight, runKey]
    )

    const dataNodeLogicProps: DataNodeLogicProps = useMemo(
        () => ({
            key: insightVizDataNodeKey(insightProps),
            query: built.query.source,
            cachedResults: built.cachedResults,
            doNotLoad: true,
            dataNodeCollectionId: `chart-bench-${runKey}`,
        }),
        [built.query.source, built.cachedResults, insightProps, runKey]
    )

    return (
        <div className="flex flex-col flex-1 min-h-0" data-attr={`real-adapters-${kind}`}>
            <BindLogic logic={insightLogic} props={insightProps}>
                <BindLogic logic={insightDataLogic} props={insightProps}>
                    <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
                        <BindLogic logic={insightVizDataLogic} props={insightProps}>
                            {kind === 'adapter-hog' ? (
                                <TrendsLineChart />
                            ) : kind === 'adapter-bar' || kind === 'adapter-bar-horizontal' ? (
                                <TrendsBarChart tooltipEnabled={tooltipEnabled} />
                            ) : kind === 'adapter-chartjs-bar-horizontal' ? (
                                <ActionsHorizontalBar />
                            ) : (
                                <ActionsLineGraph />
                            )}
                        </BindLogic>
                    </BindLogic>
                </BindLogic>
            </BindLogic>
        </div>
    )
}
