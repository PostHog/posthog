import { useValues } from 'kea'
import React from 'react'
import { ChartParams, FunnelVizType } from '~/types'
import { FunnelBarGraph } from './FunnelBarGraph'
import { FunnelHistogram } from './FunnelHistogram'
import { funnelLogic } from './funnelLogic'
import { FunnelEmptyState, FunnelInvalidFiltersEmptyState } from 'scenes/insights/EmptyStates/EmptyStates'
import { FunnelLineGraph } from 'scenes/funnels/FunnelLineGraph'
import { Loading } from 'lib/utils'
import './Funnel.scss'

export function Funnel(props: Omit<ChartParams, 'view'>): JSX.Element | null {
    const logic = funnelLogic({ dashboardItemId: props.dashboardItemId, filters: props.filters })
    const { filters, areFiltersValid, resultsLoading, isValidFunnel } = useValues(logic)
    const funnel_viz_type = filters.funnel_viz_type || props.filters.funnel_viz_type

    if (!areFiltersValid) {
        return <FunnelInvalidFiltersEmptyState />
    }
    if (resultsLoading) {
        return <Loading />
    }
    if (!isValidFunnel) {
        console.log('NOT VALID FUNNEL')
        return <FunnelEmptyState />
    }

    if (funnel_viz_type == FunnelVizType.Trends) {
        return <FunnelLineGraph {...props} />
    }

    if (funnel_viz_type == FunnelVizType.TimeToConvert) {
        return <FunnelHistogram {...props} />
    }

    return <FunnelBarGraph {...props} />
}
