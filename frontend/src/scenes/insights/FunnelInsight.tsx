import clsx from 'clsx'
import { useValues } from 'kea'
import React from 'react'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { Funnel } from 'scenes/funnels/Funnel'

export function FunnelInsight(): JSX.Element {
    const {
        isValidFunnel,
        isLoading,
        filters: { funnel_viz_type },
        areFiltersValid,
    } = useValues(funnelLogic({}))

    return (
        <div
            className={clsx('funnel-insights-container', {
                'non-empty-state': (isValidFunnel && areFiltersValid) || isLoading,
            })}
        >
            <Funnel filters={{ funnel_viz_type }} />
        </div>
    )
}
