import { useActions, useValues } from 'kea'
import React, { useEffect } from 'react'
import { ChartDisplayType, ChartParams } from '~/types'
import { FunnelBarGraph } from './FunnelBarGraph'
import { FunnelHistogram } from './FunnelHistogram'
import { funnelLogic } from './funnelLogic'

export function Funnel(props: Omit<ChartParams, 'view'>): JSX.Element | null {
    const logic = funnelLogic({ dashboardItemId: props.dashboardItemId, filters: props.filters })
    const { timeConversionBins } = useValues(logic)
    const { loadResults } = useActions(logic)

    useEffect(() => {
        loadResults()
    }, [])

    if (props.filters.display == ChartDisplayType.FunnelsTimeToConvert) {
        return timeConversionBins?.bins?.length ? <FunnelHistogram {...props} /> : null
    }

    return <FunnelBarGraph {...props} />
}
