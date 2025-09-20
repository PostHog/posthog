import './FunnelHistogram.scss'

import useSize from '@react-hook/size'
import clsx from 'clsx'
import { useValues } from 'kea'
import { useRef } from 'react'

import { hashCodeForString, humanFriendlyDuration } from 'lib/utils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { Histogram } from 'scenes/insights/views/Histogram'

import { funnelDataLogic } from './funnelDataLogic'

export function FunnelHistogram(): JSX.Element | null {
    const { insightProps, isInDashboardContext } = useValues(insightLogic)
    const { histogramGraphData } = useValues(funnelDataLogic(insightProps))

    const ref = useRef(null)
    const [width, height] = useSize(ref)

    // Must reload the entire graph on a dashboard when values change, otherwise will run into random d3 bugs
    // See: https://github.com/PostHog/posthog/pull/5259
    const key = isInDashboardContext ? hashCodeForString(JSON.stringify(histogramGraphData)) : 'staticGraph'

    if (!histogramGraphData) {
        return null
    }

    return (
        <div
            className={clsx('FunnelHistogram', {
                scrollable: !isInDashboardContext,
                'overflow-hidden': isInDashboardContext,
                'dashboard-wrapper': isInDashboardContext,
            })}
            ref={ref}
            data-attr="funnel-histogram"
        >
            <Histogram
                key={key}
                data={histogramGraphData}
                width={width}
                isDashboardItem={isInDashboardContext}
                height={height}
                formatXTickLabel={(v) => humanFriendlyDuration(v, { maxUnits: 2 })}
            />
        </div>
    )
}
