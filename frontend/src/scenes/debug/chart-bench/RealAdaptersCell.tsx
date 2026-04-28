import { BindLogic } from 'kea'
import { useMemo } from 'react'

import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { ActionsLineGraph } from 'scenes/trends/viz/ActionsLineGraph'
import { TrendsLineChart } from 'scenes/trends/viz/TrendsLineChart'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import type { DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import type { InsightLogicProps } from '~/types'

import { buildCachedInsight } from './buildCachedInsight'
import type { BenchData } from './generateBenchData'

type AdapterKind = 'adapter-hog' | 'adapter-chartjs'

interface RealAdaptersCellProps {
    kind: AdapterKind
    data: BenchData
    runKey: number
    fillArea: boolean
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
export function RealAdaptersCell({ kind, data, runKey, fillArea }: RealAdaptersCellProps): JSX.Element {
    const built = useMemo(() => buildCachedInsight(data, { fillArea }), [data, fillArea])

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
                            {kind === 'adapter-hog' ? <TrendsLineChart /> : <ActionsLineGraph />}
                        </BindLogic>
                    </BindLogic>
                </BindLogic>
            </BindLogic>
        </div>
    )
}
