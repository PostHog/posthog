import React, { useRef } from 'react'
import { useValues } from 'kea'
import clsx from 'clsx'
import useSize from '@react-hook/size'
import { hashCodeForString, humanFriendlyDuration } from 'lib/utils'
import { funnelLogic } from './funnelLogic'
import { Histogram } from 'scenes/insights/Histogram'

import './FunnelHistogram.scss'
import { insightLogic } from 'scenes/insights/insightLogic'

export function FunnelHistogram(): JSX.Element {
    const { insightProps, isViewedOnDashboard } = useValues(insightLogic)
    const logic = funnelLogic(insightProps)
    const { histogramGraphData } = useValues(logic)
    const ref = useRef(null)
    const [width, height] = useSize(ref)

    // Must reload the entire graph on a dashboard when values change, otherwise will run into random d3 bugs
    // See: https://github.com/PostHog/posthog/pull/5259
    const key = isViewedOnDashboard ? hashCodeForString(JSON.stringify(histogramGraphData)) : 'staticGraph'

    return (
        <div
            className={clsx('funnel-histogram-outer-container', { scrollable: !isViewedOnDashboard })}
            ref={ref}
            data-attr="funnel-histogram"
        >
            {!isViewedOnDashboard || width ? (
                <Histogram
                    key={key}
                    data={histogramGraphData}
                    width={width}
                    isDashboardItem={isViewedOnDashboard}
                    height={isViewedOnDashboard ? height : undefined}
                    formatXTickLabel={(v) => humanFriendlyDuration(v, 2)}
                />
            ) : null}
        </div>
    )
}
