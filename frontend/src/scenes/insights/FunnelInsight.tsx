import clsx from 'clsx'
import { useValues } from 'kea'
import { Loading } from 'lib/utils'
import React from 'react'
import { Funnel } from 'scenes/funnels/Funnel'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { FunnelInvalidFiltersEmptyState, FunnelEmptyState } from './EmptyStates'

export function FunnelInsight(): JSX.Element {
    const {
        isValidFunnel,
        isLoading,
        filters: { funnel_viz_type },
        areFiltersValid,
    } = useValues(funnelLogic({}))

    const renderFunnel = (): JSX.Element => {
        if (!areFiltersValid) {
            return <FunnelInvalidFiltersEmptyState />
        }
        if (isValidFunnel) {
            return <Funnel filters={{ funnel_viz_type }} />
        }
        return isLoading ? <div style={{ height: 50 }} /> : <FunnelEmptyState />
    }

    return (
        <div
            className={clsx('funnel-insights-container', {
                'non-empty-state': (isValidFunnel && areFiltersValid) || isLoading,
            })}
        >
            {isLoading && <Loading />}
            {renderFunnel()}
        </div>
    )
}
