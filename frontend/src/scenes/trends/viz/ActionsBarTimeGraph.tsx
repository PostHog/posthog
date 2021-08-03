import React, { useRef } from 'react'
import { useValues } from 'kea'
import useSize from '@react-hook/size'
import clsx from 'clsx'
import { ChartParams } from '~/types'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { hashCodeForString, humanFriendlyDuration, Loading } from 'lib/utils'
import { Histogram, HistogramDatum } from 'scenes/insights/Histogram'
import './ActionsBarTimeGraph.scss'

export function ActionsBarTimeGraph({
    dashboardItemId,
    view,
    filters: filtersParam,
    cachedResults,
}: ChartParams): JSX.Element {
    const logic = trendsLogic({ dashboardItemId, view, filters: filtersParam, cachedResults })
    const { filters, indexedResults, resultsLoading } = useValues(logic)
    const ref = useRef(null)
    const [width, height] = useSize(ref)

    console.log('results', indexedResults, filters)

    // const histogramGraphData: HistogramDatum[] = indexedResults

    // Must reload the entire graph on a dashboard when values change, otherwise will run into random d3 bugs
    // See: https://github.com/PostHog/posthog/pull/5259
    const key = dashboardItemId ? hashCodeForString(JSON.stringify(indexedResults)) : 'staticGraph'

    return (
        <div
            className={clsx('action-bar-time-graph-container', { scrollable: !dashboardItemId })}
            ref={ref}
            data-attr="action-bar-time-graph"
        >
            {indexedResults && !resultsLoading ? (
                indexedResults[0] ? (
                    <Histogram
                        key={key}
                        data={indexedResults as HistogramDatum[]}
                        width={width}
                        isDashboardItem={!!dashboardItemId}
                        height={dashboardItemId ? height : undefined}
                        formatXTickLabel={(v) => humanFriendlyDuration(v, 2)}
                    />
                ) : (
                    <p style={{ textAlign: 'center', marginTop: '4rem' }}>We couldn't find any matching actions.</p>
                )
            ) : (
                <Loading />
            )}
        </div>
    )
}
