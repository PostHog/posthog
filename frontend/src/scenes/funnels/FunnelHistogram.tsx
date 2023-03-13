import { useRef } from 'react'
import { useValues } from 'kea'
import clsx from 'clsx'
import useSize from '@react-hook/size'
import { hashCodeForString, humanFriendlyDuration } from 'lib/utils'
import { funnelLogic } from './funnelLogic'
import { Histogram } from 'scenes/insights/views/Histogram'
import { insightLogic } from 'scenes/insights/insightLogic'
import './FunnelHistogram.scss'
import { HistogramGraphDatum } from '~/types'
import { funnelDataLogic } from './funnelDataLogic'

export function FunnelHistogramDataExploration(): JSX.Element | null {
    const { insightProps, isInDashboardContext } = useValues(insightLogic)
    const { histogramGraphData } = useValues(funnelDataLogic(insightProps))

    return (
        <FunnelHistogramComponent isInDashboardContext={isInDashboardContext} histogramGraphData={histogramGraphData} />
    )
}

export function FunnelHistogram(): JSX.Element | null {
    const { insightProps, isInDashboardContext } = useValues(insightLogic)
    const { histogramGraphData } = useValues(funnelLogic(insightProps))

    return (
        <FunnelHistogramComponent isInDashboardContext={isInDashboardContext} histogramGraphData={histogramGraphData} />
    )
}

type FunnelHistogramComponentProps = {
    isInDashboardContext: boolean
    histogramGraphData: HistogramGraphDatum[] | null
}

export function FunnelHistogramComponent({
    isInDashboardContext,
    histogramGraphData,
}: FunnelHistogramComponentProps): JSX.Element | null {
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
            className={clsx('funnel-histogram-outer-container', {
                scrollable: !isInDashboardContext,
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
                height={isInDashboardContext ? height : undefined}
                formatXTickLabel={(v) => humanFriendlyDuration(v, 2)}
            />
        </div>
    )
}
