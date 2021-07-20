import { useActions, useValues } from 'kea'
import React, { useEffect } from 'react'
import { ChartParams, FunnelVizType } from '~/types'
import { FunnelBarGraph } from './FunnelBarGraph'
import { FunnelHistogram } from './FunnelHistogram'
import { funnelLogic } from './funnelLogic'

export function Funnel(props: Omit<ChartParams, 'view'>): JSX.Element | null {
    const logic = funnelLogic({ dashboardItemId: props.dashboardItemId, filters: props.filters })
    const { timeConversionBins, filters } = useValues(logic)
    const { loadResults } = useActions(logic)

    useEffect(() => {
        loadResults()
    }, [])

    const funnel_viz_type = filters.funnel_viz_type || props.filters.funnel_viz_type

    if (funnel_viz_type == FunnelVizType.TimeToConvert) {
        return timeConversionBins?.bins?.length ? <FunnelHistogram {...props} /> : null
    }

    return <FunnelBarGraph {...props} />
}
